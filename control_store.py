import json
import logging
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


from .control_protocol import ControlProtocolError


class ProjectDeletedError(ValueError):
    """Raised when a sync/update targets a project deleted on the server.

    The deletion tombstone makes server-side deletes authoritative: cached
    copies in any client (browser localStorage, open pages' auto-sync) must
    drop the project instead of resurrecting it."""


class ProjectSnapshotProtectionError(ValueError):
    """Raised when a client tries to replace a real graph with an empty one."""

    def __init__(self, project_id: str, revision: int):
        self.project_id = project_id
        self.revision = int(revision)
        super().__init__(
            f'拒绝用空 Project 覆盖非空服务端快照（revision {revision}）。'
            '这通常表示客户端加载/迁移失败；请先恢复服务端快照，确认后再显式清空。'
        )

ALLOWED_COMMANDS = {
    'start',
    'pause',
    'resume',
    'stop_local',
    'restart',
    'patch_parameters',
    'patch_and_restart',
    'patch_script_and_restart',
    'disable_automation',
    'acknowledge',
}
MAX_AUTO_REPAIR_COMMANDS = 3
# Cover long Claude / tool runs so inflight work is not reclaimed mid-flight.
DEFAULT_LEASE_SECONDS = 7200
MIN_LEASE_SECONDS = 60


def _clamp_lease_seconds(lease_seconds: int | float | None) -> int:
    """Clamp a lease duration; None uses the default. Non-numeric values are
    errors — silently substituting the default could reclaim an in-flight run
    (or never reclaim one) under the wrong budget."""
    if lease_seconds is None:
        return max(MIN_LEASE_SECONDS, DEFAULT_LEASE_SECONDS)
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float)):
        raise ValueError(f'lease_seconds 必须是数字，收到: {lease_seconds!r}')
    return max(MIN_LEASE_SECONDS, int(lease_seconds))


def format_loop_history_for_prompt(pointer: dict[str, Any] | None) -> str:
    """Render loop history pointer as a Claude context section."""
    if not isinstance(pointer, dict) or not pointer:
        return ''
    recent = pointer.get('recent_runs')
    if not isinstance(recent, list):
        recent = []
    repair_used = int(pointer.get('repair_commands_used') or 0)
    # Skip near-empty pointers (fresh UUID with no history yet).
    if not recent and repair_used <= 0:
        return ''
    lines = [
        '## QuantFlow 循环历史指针',
        f'本链路约第 {pointer.get("loop_round", 1)} 轮；'
        f'自动修复已用 {repair_used}/'
        f'{pointer.get("repair_commands_max", MAX_AUTO_REPAIR_COMMANDS)} '
        f'（剩余 {pointer.get("repair_commands_remaining", 0)}）。',
        'recent_runs[].artifact 仅在对应文件存在时再读（看 manifest_exists / result_exists）。',
        '【编码硬规则】产物文件均为 UTF-8；Windows 上读取用 Get-Content -Raw -Encoding UTF8（默认 ANSI/GBK 会乱码），Python 用 open(..., encoding="utf-8")，优先内置 Read 工具。',
        '文件不存在时用 error_preview/status，禁止对缺失路径 Get-Content/cat 报错。',
        '当前绑定的官方产物目录开跑时通常只有 run_meta.json；不要读尚未生成的 manifest.json/result.json。',
        '若连续失败且错误同类：换策略 / patch_and_restart，或 disable_automation；勿空转 acknowledge。',
        '```json',
        json.dumps(pointer, ensure_ascii=False, indent=2),
        '```',
    ]
    return '\n'.join(lines)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_filter_matches(event_filter: str, event_type: str) -> bool:
    """Match an event type against an edge's eventType filter.

    Semantics (explicit, no implicit surprises):
    - empty / whitespace → ONLY ``cell.run.completed`` (the intuitive
      "upstream finished successfully" trigger; a user stop or a business
      event never fires the downstream by default);
    - ``*`` → every event type (explicit opt-in to the old all-events
      behavior, e.g. for business events);
    - comma-separated list → exact membership.
    """
    accepted_types = {item.strip() for item in event_filter.split(',') if item.strip()}
    if not accepted_types:
        return event_type == 'cell.run.completed'
    if '*' in accepted_types:
        return True
    return event_type in accepted_types


class ControlStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self._warn_if_database_reset()
        self._ensure_schema()

    def _warn_if_database_reset(self) -> None:
        '''Surface a zero-byte database file instead of silently rebuilding it.

        A zero-byte file means the previous content (project snapshots, run
        history, deliveries) is gone for good - every table gets recreated
        empty. That must be loud: the user may have a backup to restore, or
        may need to know their projects only survive via the browser cache.
        '''
        try:
            size = self.path.stat().st_size
        except OSError:
            return  # file does not exist yet: first run, nothing lost
        if size == 0:
            logging.error(
                'QuantFlow 数据库文件 %s 存在但大小为 0 字节：原内容（Project 快照、运行历史、'
                '交付记录）已丢失，服务将重新初始化空数据库。若这不是预期行为，'
                '请用备份恢复该文件后重启。',
                self.path,
            )

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self.lock, self._connect() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS project_snapshot (
                    project_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_snapshot_history (
                    project_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, revision)
                );
                CREATE INDEX IF NOT EXISTS idx_project_snapshot_history_time
                    ON project_snapshot_history(project_id, revision DESC);
                CREATE TABLE IF NOT EXISTS event_log (
                    event_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source_cell_id TEXT,
                    source_run_id TEXT,
                    correlation_id TEXT,
                    causation_id TEXT,
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_event_project_time
                    ON event_log(project_id, occurred_at);
                CREATE TABLE IF NOT EXISTS command_queue (
                    command_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    target_cell_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL,
                    expected_revision INTEGER,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    reason TEXT,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_command_target_status
                    ON command_queue(project_id, target_cell_id, status);
                CREATE TABLE IF NOT EXISTS cell_state (
                    project_id TEXT NOT NULL,
                    cell_id TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    next_run_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, cell_id)
                );
                CREATE INDEX IF NOT EXISTS idx_cell_state_next_run
                    ON cell_state(next_run_at);
                CREATE TABLE IF NOT EXISTS cell_run (
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    cell_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    executor_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    attempt INTEGER NOT NULL DEFAULT 1,
                    delivery_id TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_cell_run_cell_status
                    ON cell_run(project_id, cell_id, status);
                CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_cell_run
                    ON cell_run(project_id, cell_id)
                    WHERE status IN ('queued', 'running');
                CREATE TABLE IF NOT EXISTS run_event (
                    sequence_no INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_run_event_run_sequence
                    ON run_event(run_id, sequence_no);
                CREATE TABLE IF NOT EXISTS event_delivery (
                    delivery_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    target_cell_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(event_id, connection_id)
                );
                CREATE INDEX IF NOT EXISTS idx_delivery_status_lease
                    ON event_delivery(status, lease_expires_at, created_at);
                CREATE TABLE IF NOT EXISTS schedule_lease (
                    project_id TEXT NOT NULL,
                    cell_id TEXT NOT NULL,
                    lease_owner TEXT NOT NULL,
                    lease_expires_at TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, cell_id)
                );
                CREATE TABLE IF NOT EXISTS command_lease (
                    command_id TEXT PRIMARY KEY,
                    lease_owner TEXT NOT NULL,
                    lease_expires_at TEXT NOT NULL,
                    acquired_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_loop_reset (
                    project_id TEXT PRIMARY KEY,
                    reset_at TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS project_tombstone (
                    project_id TEXT PRIMARY KEY,
                    deleted_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS flow_registry (
                    project_id TEXT NOT NULL,
                    cell_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL DEFAULT '',
                    registered_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, cell_id)
                );
                CREATE INDEX IF NOT EXISTS idx_flow_registry_expires
                    ON flow_registry(expires_at);
                DROP TABLE IF EXISTS external_job_lease;
                DROP TABLE IF EXISTS external_job;
            ''')
            command_columns = {
                row['name'] for row in connection.execute('PRAGMA table_info(command_queue)').fetchall()
            }
            if 'correlation_id' not in command_columns:
                connection.execute(
                    "ALTER TABLE command_queue ADD COLUMN correlation_id TEXT NOT NULL DEFAULT ''"
                )
            delivery_columns = {
                row['name'] for row in connection.execute('PRAGMA table_info(event_delivery)').fetchall()
            }
            if 'next_claim_at' not in delivery_columns:
                connection.execute(
                    'ALTER TABLE event_delivery ADD COLUMN next_claim_at TEXT'
                )

    def sync_project(
        self,
        project: dict[str, Any],
        expected_revision: int | None = None,
        *,
        allow_empty_snapshot: bool = False,
    ) -> int:
        project_id = str(project.get('id') or '').strip()
        if not project_id:
            raise ValueError('project.id 不能为空')
        with self.lock, self._connect() as connection:
            tombstone = connection.execute(
                'SELECT deleted_at FROM project_tombstone WHERE project_id = ?',
                (project_id,),
            ).fetchone()
            if tombstone:
                raise ProjectDeletedError(
                    f'该项目已在服务端删除（{tombstone["deleted_at"]}），本地缓存应清理而不是重建'
                )
            row = connection.execute(
                'SELECT revision, snapshot_json FROM project_snapshot WHERE project_id = ?',
                (project_id,),
            ).fetchone()
            current_revision = int(row['revision']) if row else 0
            is_new_project = current_revision == 0
            if expected_revision is not None and expected_revision != current_revision:
                raise ValueError(f'Project revision 冲突: 当前 {current_revision}，提交 {expected_revision}')
            previous_triggers: dict[str, str] = {}
            if row:
                try:
                    previous = json.loads(row['snapshot_json'] or '{}')
                except (TypeError, json.JSONDecodeError) as exc:
                    # Corrupt persisted state must be visible, not treated as an
                    # empty project (which would pause every interval cell and
                    # hide the real reason from the user).
                    raise ValueError(
                        f'Project 快照数据损坏（{exc}），无法安全同步。'
                        '请删除该 Project 后重新绑定，或检查数据库文件。'
                    ) from exc
                for cell in (previous.get('cells') if isinstance(previous, dict) else None) or []:
                    if isinstance(cell, dict) and cell.get('id'):
                        previous_triggers[str(cell['id'])] = str(cell.get('triggerType') or '')
                previous_cells = previous.get('cells') if isinstance(previous, dict) else []
                previous_connections = previous.get('connections') if isinstance(previous, dict) else []
                submitted_cells = project.get('cells') if isinstance(project, dict) else []
                submitted_connections = project.get('connections') if isinstance(project, dict) else []
                previous_has_graph = bool(previous_cells or previous_connections)
                submitted_is_empty = not submitted_cells and not submitted_connections
                if previous_has_graph and submitted_is_empty and not allow_empty_snapshot:
                    raise ProjectSnapshotProtectionError(project_id, current_revision)
            revision = current_revision + 1
            if row:
                connection.execute('''
                    INSERT OR REPLACE INTO project_snapshot_history(
                        project_id, revision, snapshot_json, updated_at
                    ) VALUES (?, ?, ?, ?)
                ''', (
                    project_id,
                    current_revision,
                    row['snapshot_json'],
                    _now(),
                ))
                connection.execute('''
                    DELETE FROM project_snapshot_history
                    WHERE project_id = ?
                      AND revision NOT IN (
                          SELECT revision FROM project_snapshot_history
                          WHERE project_id = ? ORDER BY revision DESC LIMIT 20
                      )
                ''', (project_id, project_id))
            connection.execute('''
                INSERT INTO project_snapshot(project_id, revision, snapshot_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    revision = excluded.revision,
                    snapshot_json = excluded.snapshot_json,
                    updated_at = excluded.updated_at
            ''', (project_id, revision, json.dumps(project, ensure_ascii=False), _now()))
            # Pause interval cells that are brand-new to this project snapshot as
            # interval (clone, newly added, or just switched from manual/event).
            # Otherwise the scheduler auto-arms next_run_at=now and fires while
            # the user is still typing goal/context.
            now = _now()
            for cell in project.get('cells') or []:
                if not isinstance(cell, dict):
                    continue
                if str(cell.get('triggerType') or '') != 'interval':
                    continue
                cell_id = str(cell.get('id') or '').strip()
                if not cell_id:
                    continue
                was_interval = previous_triggers.get(cell_id) == 'interval'
                if not is_new_project and was_interval:
                    continue
                reason = (
                    '项目复制后默认停止周期，请手动恢复'
                    if is_new_project
                    else '已切换为周期执行，确认配置后请点「恢复周期」'
                )
                pause = {
                    'paused_at': now,
                    'reason': reason,
                    'run_id': '',
                    'status': 'paused',
                }
                connection.execute('''
                    INSERT INTO cell_state(project_id, cell_id, revision, state_json, next_run_at, updated_at)
                    VALUES (?, ?, 0, ?, NULL, ?)
                    ON CONFLICT(project_id, cell_id) DO UPDATE SET
                        state_json = excluded.state_json,
                        next_run_at = NULL,
                        updated_at = excluded.updated_at
                ''', (project_id, cell_id, json.dumps({'automation_paused': pause}, ensure_ascii=False), now))
            connection.commit()
        return revision

    def list_project_snapshot_history(
        self, project_id: str, *, limit: int = 20,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 20), 100))
        with self.lock, self._connect() as connection:
            rows = connection.execute('''
                SELECT project_id, revision, snapshot_json, updated_at
                FROM project_snapshot_history
                WHERE project_id = ?
                ORDER BY revision DESC LIMIT ?
            ''', (project_id, limit)).fetchall()
        return [
            {
                'project_id': row['project_id'],
                'revision': int(row['revision']),
                'project': json.loads(row['snapshot_json']),
                'updated_at': row['updated_at'],
            }
            for row in rows
        ]

    def get_project_snapshot(self, project_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            row = connection.execute('''
                SELECT revision, snapshot_json, updated_at FROM project_snapshot WHERE project_id = ?
            ''', (project_id,)).fetchone()
        if not row:
            return None
        return {
            'project_id': project_id, 'revision': row['revision'],
            'project': json.loads(row['snapshot_json']), 'updated_at': row['updated_at'],
        }

    def list_project_snapshots(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute('''
                SELECT project_id, revision, snapshot_json, updated_at
                FROM project_snapshot ORDER BY updated_at DESC
            ''').fetchall()
        return [{
            'project_id': row['project_id'],
            'revision': row['revision'],
            'project': json.loads(row['snapshot_json']),
            'updated_at': row['updated_at'],
        } for row in rows]

    def delete_project(self, project_id: str) -> bool:
        with self.lock, self._connect() as connection:
            row = connection.execute(
                'SELECT revision, snapshot_json FROM project_snapshot WHERE project_id = ?', (project_id,),
            ).fetchone()
            if not row:
                return False
            connection.execute('''
                INSERT OR REPLACE INTO project_snapshot_history(
                    project_id, revision, snapshot_json, updated_at
                ) VALUES (?, ?, ?, ?)
            ''', (project_id, int(row['revision']), row['snapshot_json'], _now()))
            run_ids = [item['run_id'] for item in connection.execute(
                'SELECT run_id FROM cell_run WHERE project_id = ?', (project_id,),
            ).fetchall()]
            if run_ids:
                placeholders = ', '.join('?' for _ in run_ids)
                connection.execute(f'DELETE FROM run_event WHERE run_id IN ({placeholders})', run_ids)
            connection.execute('DELETE FROM command_lease WHERE command_id IN (SELECT command_id FROM command_queue WHERE project_id = ?)', (project_id,))
            connection.execute('DELETE FROM event_delivery WHERE project_id = ?', (project_id,))
            connection.execute('DELETE FROM schedule_lease WHERE project_id = ?', (project_id,))
            connection.execute('DELETE FROM command_queue WHERE project_id = ?', (project_id,))
            connection.execute('DELETE FROM cell_run WHERE project_id = ?', (project_id,))
            connection.execute('DELETE FROM cell_state WHERE project_id = ?', (project_id,))
            connection.execute('DELETE FROM event_log WHERE project_id = ?', (project_id,))
            connection.execute('DELETE FROM project_loop_reset WHERE project_id = ?', (project_id,))
            connection.execute('DELETE FROM project_snapshot WHERE project_id = ?', (project_id,))
            # Deletion tombstone: any later sync attempt for this project id is
            # rejected so cached client copies cannot resurrect it.
            connection.execute('''
                INSERT INTO project_tombstone(project_id, deleted_at) VALUES (?, ?)
                ON CONFLICT(project_id) DO UPDATE SET deleted_at = excluded.deleted_at
            ''', (project_id, _now()))
            connection.commit()
        return True

    def _loop_reset_at(self, connection: sqlite3.Connection, project_id: str) -> str:
        row = connection.execute(
            'SELECT reset_at FROM project_loop_reset WHERE project_id = ?',
            (project_id,),
        ).fetchone()
        return str(row['reset_at'] or '') if row else ''

    def _count_repair_commands(
        self, connection: sqlite3.Connection, project_id: str, correlation_id: str,
    ) -> int:
        """Count repair-budget commands after the latest Project loop-history reset."""
        correlation_id = str(correlation_id or '').strip()
        if not correlation_id:
            return 0
        reset_at = self._loop_reset_at(connection, project_id)
        if reset_at:
            return int(connection.execute('''
                SELECT COUNT(*) AS count FROM command_queue
                WHERE project_id = ? AND correlation_id = ?
                  AND action NOT IN ('disable_automation', 'acknowledge')
                  AND status NOT IN ('forgotten', 'cancelled')
                  AND created_at >= ?
            ''', (project_id, correlation_id, reset_at)).fetchone()['count'])
        return int(connection.execute('''
            SELECT COUNT(*) AS count FROM command_queue
            WHERE project_id = ? AND correlation_id = ?
              AND action NOT IN ('disable_automation', 'acknowledge')
              AND status NOT IN ('forgotten', 'cancelled')
        ''', (project_id, correlation_id)).fetchone()['count'])

    def clear_project_loop_history(
        self, project_id: str, reason: str = '用户重置状态',
    ) -> dict[str, Any]:
        """Forget repair/command history so the next loop starts with a clean pointer."""
        project_id = str(project_id or '').strip()
        reason = str(reason or '用户重置状态').strip() or '用户重置状态'
        now = _now()
        with self.lock, self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('''
                INSERT INTO project_loop_reset(project_id, reset_at, reason)
                VALUES (?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    reset_at = excluded.reset_at,
                    reason = excluded.reason
            ''', (project_id, now, reason))
            cursor = connection.execute('''
                UPDATE command_queue
                SET status = 'forgotten',
                    reason = CASE
                        WHEN reason IS NULL OR reason = '' THEN ?
                        ELSE reason || ' · ' || ?
                    END,
                    updated_at = ?
                WHERE project_id = ? AND status NOT IN ('forgotten')
            ''', (reason, reason, now, project_id))
            forgotten = int(cursor.rowcount or 0)
            connection.execute(
                'DELETE FROM command_lease WHERE command_id IN '
                '(SELECT command_id FROM command_queue WHERE project_id = ?)',
                (project_id,),
            )
            connection.commit()
        return {
            'reset_at': now,
            'forgotten_commands': forgotten,
            'reason': reason,
        }

    def get_project_loop_reset_at(self, project_id: str) -> str:
        with self.lock, self._connect() as connection:
            return self._loop_reset_at(connection, project_id)

    def append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        project_id = str(event.get('project_id') or '').strip()
        event_type = str(event.get('type') or '').strip()
        if not project_id or not event_type:
            raise ValueError('event.project_id 和 event.type 不能为空')
        stored = {
            'schema_version': '1',
            'event_id': str(event.get('event_id') or uuid.uuid4()),
            'project_id': project_id,
            'type': event_type,
            'source_cell_id': str(event.get('source_cell_id') or ''),
            'source_run_id': str(event.get('source_run_id') or ''),
            'correlation_id': str(event.get('correlation_id') or ''),
            'causation_id': str(event.get('causation_id') or ''),
            'payload': event.get('payload') if isinstance(event.get('payload'), dict) else {},
            'occurred_at': str(event.get('occurred_at') or _now()),
        }
        with self.lock, self._connect() as connection:
            existing_event = connection.execute(
                'SELECT * FROM event_log WHERE event_id = ?', (stored['event_id'],),
            ).fetchone()
            if existing_event:
                try:
                    existing_payload = json.loads(existing_event['payload_json'])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ValueError(f'事件记录损坏（{exc}），无法校验幂等性') from exc
                same_event = (
                    existing_event['project_id'] == stored['project_id'] and
                    existing_event['event_type'] == stored['type'] and
                    existing_event['source_cell_id'] == stored['source_cell_id'] and
                    existing_event['source_run_id'] == stored['source_run_id'] and
                    existing_event['correlation_id'] == stored['correlation_id'] and
                    existing_event['causation_id'] == stored['causation_id'] and
                    existing_payload == stored['payload']
                )
                if not same_event:
                    raise ValueError('event_id 已用于不同事件')
                return stored
            snapshot = connection.execute(
                'SELECT snapshot_json FROM project_snapshot WHERE project_id = ?',
                (stored['project_id'],),
            ).fetchone()
            if not snapshot:
                raise ValueError('Project Snapshot 不存在')
            project = json.loads(snapshot['snapshot_json'])
            control_commands = self._parse_control_commands(project, stored)
            connection.execute('''
                INSERT INTO event_log(
                    event_id, project_id, event_type, source_cell_id, source_run_id,
                    correlation_id, causation_id, payload_json, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                stored['event_id'], stored['project_id'], stored['type'],
                stored['source_cell_id'], stored['source_run_id'],
                stored['correlation_id'], stored['causation_id'],
                json.dumps(stored['payload'], ensure_ascii=False), stored['occurred_at'],
            ))
            now = _now()
            for edge in project.get('connections', []):
                if edge.get('kind') != 'event':
                    continue
                if edge.get('sourceCellId') != stored['source_cell_id']:
                    continue
                event_filter = str(edge.get('eventType') or '').strip()
                if not _event_filter_matches(event_filter, stored['type']):
                    continue
                connection.execute('''
                    INSERT OR IGNORE INTO event_delivery(
                        delivery_id, event_id, connection_id, project_id,
                        target_cell_id, status, attempt, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                ''', (
                    str(uuid.uuid4()), stored['event_id'], str(edge.get('id') or ''),
                    stored['project_id'], str(edge.get('targetCellId') or ''), now, now,
                ))
            repair_used = 0
            correlation_id = str(stored.get('correlation_id') or '').strip()
            # Empty correlation_id must not share one project-wide repair bucket.
            if correlation_id:
                repair_used = self._count_repair_commands(
                    connection, stored['project_id'], correlation_id,
                )
            for command in control_commands:
                # Escape hatches / non-repairs must not consume the auto-repair budget.
                counts_toward_budget = (
                    command['action'] not in {'disable_automation', 'acknowledge'}
                    and bool(str(command.get('correlation_id') or '').strip())
                )
                if counts_toward_budget:
                    if repair_used >= MAX_AUTO_REPAIR_COMMANDS:
                        raise ControlProtocolError(
                            f'同一链路自动修复次数已达到 {MAX_AUTO_REPAIR_COMMANDS} 次，'
                            '已停止自动控制。请输出 disable_automation，'
                            '或在 UI 重置 Project 状态清空循环历史后再试。'
                        )
                    repair_used += 1
                existing = connection.execute(
                    'SELECT project_id, target_cell_id, correlation_id, action, expected_revision, payload_json '
                    'FROM command_queue WHERE idempotency_key = ?',
                    (command['idempotency_key'],),
                ).fetchone()
                if existing:
                    if not (
                        existing['project_id'] == stored['project_id'] and
                        existing['target_cell_id'] == command['target_cell_id'] and
                        existing['correlation_id'] == command['correlation_id'] and
                        existing['action'] == command['action'] and
                        existing['expected_revision'] == command['expected_revision'] and
                        json.loads(existing['payload_json']) == command['payload']
                    ):
                        raise ValueError('控制命令 idempotency_key 已用于不同命令')
                    continue
                command_now = _now()
                connection.execute('''
                    INSERT INTO command_queue(
                        command_id, project_id, target_cell_id, correlation_id, action, expected_revision,
                        idempotency_key, reason, payload_json, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                ''', (
                    str(uuid.uuid4()), stored['project_id'], command['target_cell_id'],
                    command['correlation_id'], command['action'], command['expected_revision'], command['idempotency_key'],
                    command['reason'], json.dumps(command['payload'], ensure_ascii=False),
                    command_now, command_now,
                ))
            connection.commit()
        return stored

    def replay_event_delivery(self, project_id: str, source_cell_id: str, target_cell_id: str) -> str:
        """Deliver the source cell's LAST completion event to a NEW event cell.

        Used by breakpoint-resume for brand-new upstream-event cells: the
        source already succeeded (its completion event is persisted in
        event_log), so instead of re-running the whole upstream we replay that
        event through the same delivery path the scheduler consumes. Returns:
          'replayed'       - delivery created, scheduler will start the target
          'already_pending'- a delivery for this event+target is in flight
          'no_event'       - source has no matching completion event (or the
                             edge filters another type): upstream never ran.
        Raises ValueError when the project/edge is missing."""
        project_id = str(project_id or '').strip()
        source_cell_id = str(source_cell_id or '').strip()
        target_cell_id = str(target_cell_id or '').strip()
        if not project_id or not source_cell_id or not target_cell_id:
            raise ValueError('project_id、source_cell_id、target_cell_id 不能为空')
        with self.lock, self._connect() as connection:
            snapshot = connection.execute(
                'SELECT snapshot_json FROM project_snapshot WHERE project_id = ?',
                (project_id,),
            ).fetchone()
            if not snapshot:
                raise ValueError('Project Snapshot 不存在')
            project = json.loads(snapshot['snapshot_json'])
            edge = None
            for item in project.get('connections', []):
                if (
                    item.get('kind') == 'event'
                    and item.get('sourceCellId') == source_cell_id
                    and item.get('targetCellId') == target_cell_id
                ):
                    edge = item
                    break
            if edge is None:
                raise ValueError('事件边不存在')
            event_filter = str(edge.get('eventType') or '').strip()
            if not _event_filter_matches(event_filter, 'cell.run.completed'):
                return 'no_event'
            row = connection.execute('''
                SELECT event_id, occurred_at FROM event_log
                WHERE project_id = ? AND source_cell_id = ? AND event_type = 'cell.run.completed'
                ORDER BY occurred_at DESC, event_id DESC LIMIT 1
            ''', (project_id, source_cell_id)).fetchone()
            if not row:
                return 'no_event'
            event_id = row['event_id']
            existing = connection.execute('''
                SELECT 1 FROM event_delivery
                WHERE event_id = ? AND target_cell_id = ?
                AND status IN ('pending', 'claimed', 'running')
            ''', (event_id, target_cell_id)).fetchone()
            if existing:
                return 'already_pending'
            now = _now()
            connection.execute('''
                INSERT INTO event_delivery(
                    delivery_id, event_id, connection_id, project_id,
                    target_cell_id, status, attempt, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)
            ''', (
                str(uuid.uuid4()), event_id, str(edge.get('id') or ''),
                project_id, target_cell_id, now, now,
            ))
            connection.commit()
        return 'replayed'
    @staticmethod
    def _parse_control_commands(project: dict[str, Any], event: dict[str, Any]) -> list[dict[str, Any]]:
        if event['type'] != 'cell.run.completed':
            return []
        from .control_protocol import (
            outgoing_control_edges,
            validate_control_result,
        )

        control_edges = outgoing_control_edges(project, event['source_cell_id'])
        if not control_edges:
            return []

        payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
        raw_result = payload.get('result')
        # Prefer on-disk artifact (standard handoff); keep inline result for backward compatibility.
        if raw_result is None and isinstance(payload.get('artifact'), dict):
            from .artifact_store import extract_control_result, load_result_document
            working_directory = str(
                payload.get('working_directory')
                or project.get('workingDirectory')
                or ''
            )
            try:
                result_doc = load_result_document(working_directory, payload.get('artifact'))
                raw_result = extract_control_result(result_doc, fallback=None)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise ControlProtocolError(f'无法从 artifact 读取控制结果: {exc}') from exc
        return validate_control_result(
            project,
            event['source_cell_id'],
            raw_result,
            event_id=str(event.get('event_id') or ''),
            correlation_id=str(event.get('correlation_id') or ''),
        )

    def commit_tool_result(
        self, project_id: str, source_cell_id: str, source_run_id: str,
        correlation_id: str, state_update: dict[str, Any], events: list[dict[str, Any]],
        expected_state_revision: int, lease_owner: str = '',
    ) -> dict[str, Any]:
        stored_events = []
        conflicts: list[str] = []
        with self.lock, self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            snapshot = connection.execute(
                'SELECT snapshot_json FROM project_snapshot WHERE project_id = ?', (project_id,),
            ).fetchone()
            project = json.loads(snapshot['snapshot_json']) if snapshot else {}
            state_row = connection.execute('''
                SELECT revision, state_json, next_run_at FROM cell_state
                WHERE project_id = ? AND cell_id = ?
            ''', (project_id, source_cell_id)).fetchone()
            current_revision = int(state_row['revision']) if state_row else 0
            if current_revision != int(expected_state_revision):
                raise ValueError(
                    f'Cell state revision 冲突: 当前 {current_revision}，提交 {expected_state_revision}'
                )
            current_state = json.loads(state_row['state_json']) if state_row else {}
            merged_state = {**current_state, **state_update}
            new_revision = current_revision + 1
            connection.execute('''
                INSERT INTO cell_state(project_id, cell_id, revision, state_json, next_run_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, cell_id) DO UPDATE SET
                    revision = excluded.revision,
                    state_json = excluded.state_json,
                    next_run_at = excluded.next_run_at,
                    updated_at = excluded.updated_at
            ''', (
                project_id, source_cell_id, new_revision,
                json.dumps(merged_state, ensure_ascii=False),
                state_row['next_run_at'] if state_row else None, _now(),
            ))
            for event_index, raw_event in enumerate(events):
                event_type = str(raw_event.get('type') or '').strip()
                if not event_type:
                    raise ValueError('工具返回的 Event 缺少 type')
                stored = {
                    'schema_version': '1',
                    'event_id': str(raw_event.get('event_id') or f'tool:{source_run_id}:{event_index}:{event_type}'),
                    'project_id': project_id,
                    'type': event_type,
                    'source_cell_id': source_cell_id,
                    'source_run_id': source_run_id,
                    'correlation_id': correlation_id,
                    'causation_id': str(raw_event.get('causation_id') or ''),
                    'payload': raw_event.get('payload') if isinstance(raw_event.get('payload'), dict) else {},
                    'occurred_at': str(raw_event.get('occurred_at') or _now()),
                }
                cursor = connection.execute('''
                    INSERT OR IGNORE INTO event_log(
                        event_id, project_id, event_type, source_cell_id, source_run_id,
                        correlation_id, causation_id, payload_json, occurred_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    stored['event_id'], project_id, stored['type'], source_cell_id,
                    source_run_id, correlation_id, stored['causation_id'],
                    json.dumps(stored['payload'], ensure_ascii=False), stored['occurred_at'],
                ))
                if not cursor.rowcount:
                    # Stable event_id already exists (at-least-once replay).
                    # Do not silently drop a *different* payload — surface it.
                    existing = connection.execute(
                        'SELECT payload_json FROM event_log WHERE event_id = ?',
                        (stored['event_id'],),
                    ).fetchone()
                    try:
                        existing_payload = json.loads(existing['payload_json']) if existing else None
                    except (TypeError, json.JSONDecodeError):
                        existing_payload = None
                    if existing_payload != stored['payload']:
                        conflicts.append(
                            f'业务事件 {stored["event_id"]} 已存在且内容不同，本次已忽略（重试改动了数据？）',
                        )
                if cursor.rowcount:
                    now = _now()
                    for edge in project.get('connections', []):
                        if edge.get('kind') != 'event' or edge.get('sourceCellId') != source_cell_id:
                            continue
                        event_filter = str(edge.get('eventType') or '').strip()
                        if not _event_filter_matches(event_filter, stored['type']):
                            continue
                        connection.execute('''
                            INSERT OR IGNORE INTO event_delivery(
                                delivery_id, event_id, connection_id, project_id,
                                target_cell_id, status, attempt, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                        ''', (
                            str(uuid.uuid4()), stored['event_id'], str(edge.get('id') or ''),
                            project_id, str(edge.get('targetCellId') or ''), now, now,
                        ))
                stored_events.append(stored)
            if lease_owner:
                connection.execute('''
                    DELETE FROM schedule_lease
                    WHERE project_id = ? AND cell_id = ? AND lease_owner = ?
                ''', (project_id, source_cell_id, lease_owner))
            connection.commit()
        return {
            'events': stored_events,
            'state': merged_state,
            'state_revision': new_revision,
            'conflicts': conflicts,
        }

    # ------------------------------------------------------------------
    # Flow registry: frontend runProjectFlow member registration so the
    # scheduler does not race the flow (interval leases on the same cells).
    # ------------------------------------------------------------------

    def register_flow_cells(
        self, project_id: str, cell_ids: list[Any], correlation_id: str = '',
        *, ttl_seconds: int = 1800,
    ) -> dict[str, Any]:
        project_id = str(project_id or '').strip()
        if not project_id:
            raise ValueError('project_id 不能为空')
        cells = [
            str(cid) for cid in (cell_ids or []) if str(cid or '').strip()
        ]
        ttl = max(60, min(int(ttl_seconds or 1800), 4 * 3600))
        now = _now()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
        with self.lock, self._connect() as connection:
            connection.execute(
                'DELETE FROM flow_registry WHERE project_id = ?', (project_id,),
            )
            for cell_id in cells:
                connection.execute('''
                    INSERT INTO flow_registry(
                        project_id, cell_id, correlation_id, registered_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?)
                ''', (project_id, cell_id, correlation_id, now, expires))
            connection.commit()
        return {'project_id': project_id, 'cell_ids': cells, 'expires_at': expires}

    def clear_flow_registration(self, project_id: str) -> None:
        with self.lock, self._connect() as connection:
            connection.execute(
                'DELETE FROM flow_registry WHERE project_id = ?', (project_id,),
            )
            connection.commit()

    def list_flow_cells(self, project_id: str) -> list[dict[str, Any]]:
        """Active (non-expired) flow members for a project."""
        with self.lock, self._connect() as connection:
            rows = connection.execute('''
                SELECT cell_id, correlation_id, expires_at FROM flow_registry
                WHERE project_id = ? AND expires_at > ?
            ''', (project_id, _now())).fetchall()
        return [dict(row) for row in rows]

    def purge_expired_flows(self) -> int:
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                'DELETE FROM flow_registry WHERE expires_at <= ?', (_now(),),
            )
            connection.commit()
            return int(cursor.rowcount or 0)

    def create_cell_run(self, run_id: str, cell: dict[str, Any]) -> None:
        try:
            with self.lock, self._connect() as connection:
                connection.execute('''
                    INSERT INTO cell_run(
                        run_id, project_id, cell_id, correlation_id, executor_type,
                        status, input_json, attempt, delivery_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                ''', (
                    run_id, cell['project_id'], cell['cell_id'], cell['correlation_id'],
                    cell['executor_type'], json.dumps(cell, ensure_ascii=False),
                    int(cell.get('attempt', 1)), cell.get('delivery_id'), _now(),
                ))
                connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError('该 Cell 已有持久化的运行中任务') from exc

    def recover_incomplete_runs(self) -> int:
        with self.lock, self._connect() as connection:
            rows = connection.execute('''
                SELECT run_id, project_id, cell_id, input_json FROM cell_run
                WHERE status IN ('queued', 'running')
            ''').fetchall()
            cursor = connection.execute('''
                UPDATE cell_run SET status = 'interrupted',
                    error = CASE WHEN error = '' THEN '服务重启导致运行中断' ELSE error END,
                    finished_at = ? WHERE status IN ('queued', 'running')
            ''', (_now(),))
            connection.commit()
            count = cursor.rowcount
        # Pause interval automation for interrupted runs so restart does not silently resume.
        for row in rows:
            try:
                payload = json.loads(row['input_json'] or '{}')
            except json.JSONDecodeError as exc:
                # Unparseable run input: we cannot tell whether the cell was an
                # interval cell. Fail-closed — pause the schedule and say why.
                self.mark_interval_paused(
                    row['project_id'], row['cell_id'],
                    reason=f'服务重启后运行输入数据损坏（{exc}），已暂停自动调度',
                    run_id=row['run_id'], status='interrupted',
                )
                continue
            trigger = payload.get('trigger') if isinstance(payload.get('trigger'), dict) else {}
            configured = str(payload.get('configured_trigger_type') or trigger.get('type') or '')
            if trigger.get('type') == 'interval' or configured == 'interval':
                self.mark_interval_paused(
                    row['project_id'], row['cell_id'],
                    reason='服务重启导致运行中断，已暂停自动调度',
                    run_id=row['run_id'], status='interrupted',
                )
        return count

    def list_interrupted_runs(self, *, limit: int = 40) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute('''
                SELECT run_id, project_id, cell_id, input_json, error, finished_at
                FROM cell_run
                WHERE status = 'interrupted'
                ORDER BY COALESCE(finished_at, started_at, created_at) DESC
                LIMIT ?
            ''', (max(1, min(int(limit), 200)),)).fetchall()
        return [dict(row) for row in rows]

    def recover_inflight_deliveries(self) -> int:
        with self.lock, self._connect() as connection:
            cursor = connection.execute('''
                UPDATE event_delivery SET status = 'pending', lease_owner = NULL,
                    lease_expires_at = NULL, next_claim_at = NULL, updated_at = ?
                WHERE status = 'inflight'
            ''', (_now(),))
            connection.commit()
            return cursor.rowcount

    def update_cell_run(self, run_id: str, status: str, result: dict[str, Any] | None = None, error: str = '') -> None:
        terminal = status in {'completed', 'failed', 'stopped', 'interrupted', 'control_protocol_failed'}
        with self.lock, self._connect() as connection:
            connection.execute('''
                UPDATE cell_run SET status = ?, result_json = ?, error = ?,
                    started_at = CASE WHEN ? = 'running' AND started_at IS NULL THEN ? ELSE started_at END,
                    finished_at = CASE WHEN ? THEN ? ELSE finished_at END
                WHERE run_id = ?
            ''', (
                status, json.dumps(result or {}, ensure_ascii=False), error,
                status, _now(), 1 if terminal else 0, _now(), run_id,
            ))
            connection.commit()

    def finalize_cell_run(
        self, run_id: str, status: str, result: dict[str, Any],
        error: str, terminal_event: dict[str, Any],
    ) -> int:
        with self.lock, self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('''
                UPDATE cell_run SET status = ?, result_json = ?, error = ?, finished_at = ?
                WHERE run_id = ?
            ''', (status, json.dumps(result, ensure_ascii=False), error, _now(), run_id))
            cursor = connection.execute('''
                INSERT INTO run_event(run_id, event_json, created_at) VALUES (?, ?, ?)
            ''', (run_id, json.dumps(terminal_event, ensure_ascii=False), _now()))
            connection.commit()
            return int(cursor.lastrowid)

    def append_run_event(self, run_id: str, event: dict[str, Any]) -> int:
        with self.lock, self._connect() as connection:
            cursor = connection.execute('''
                INSERT INTO run_event(run_id, event_json, created_at) VALUES (?, ?, ?)
            ''', (run_id, json.dumps(event, ensure_ascii=False), _now()))
            connection.commit()
            return int(cursor.lastrowid)

    def list_run_events(self, run_id: str, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute('''
                SELECT sequence_no, event_json, created_at FROM run_event
                WHERE run_id = ? AND sequence_no > ? ORDER BY sequence_no ASC LIMIT ?
            ''', (run_id, max(0, after), max(1, min(limit, 2000)))).fetchall()
        return [{
            'sequence_no': row['sequence_no'],
            'event': json.loads(row['event_json']),
            'created_at': row['created_at'],
        } for row in rows]

    def get_cell_run(self, run_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            row = connection.execute('SELECT * FROM cell_run WHERE run_id = ?', (run_id,)).fetchone()
        if not row:
            return None
        try:
            result = json.loads(row['result_json'])
            input_data = json.loads(row['input_json'])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f'运行记录数据损坏（{exc}），无法读取 run {row["run_id"]}') from exc
        run = {
            'run_id': row['run_id'], 'project_id': row['project_id'], 'cell_id': row['cell_id'],
            'correlation_id': row['correlation_id'], 'executor_type': row['executor_type'],
            'status': row['status'], 'input': input_data,
            'result': result, 'error': row['error'],
            'attempt': row['attempt'], 'delivery_id': row['delivery_id'],
            'created_at': row['created_at'], 'started_at': row['started_at'],
            'finished_at': row['finished_at'],
        }
        session_id = ''
        if isinstance(result, dict):
            session_id = str(result.get('session_id') or '').strip()
        if not session_id:
            session_id = self.get_claude_session_id(str(row['run_id']))
        if session_id:
            run['claude_session_id'] = session_id
        return run

    def get_claude_session_id(self, run_id: str) -> str:
        """Best-effort agent session id from stream events.

        Claude Code uses ``session_id``; Codex CLI uses ``thread_id``
        (e.g. ``thread.started``). Stored under the shared resume field
        ``claude_session_id`` / ``claude_resume_session_id``.
        """
        run_id = str(run_id or '').strip()
        if not run_id:
            return ''
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                '''
                SELECT event_json FROM run_event
                WHERE run_id = ?
                  AND (
                    event_json LIKE '%session_id%'
                    OR event_json LIKE '%thread_id%'
                    OR event_json LIKE '%"thread.started"%'
                  )
                ORDER BY sequence_no DESC
                LIMIT 120
                ''',
                (run_id,),
            ).fetchall()
        for row in rows:
            try:
                event = json.loads(row['event_json'])
            except (TypeError, json.JSONDecodeError):
                continue
            payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
            if not isinstance(payload, dict):
                continue
            sid = str(
                payload.get('session_id')
                or payload.get('thread_id')
                or ''
            ).strip()
            if sid:
                return sid
            # Some stream frames nest session id under message / result fields.
            for key in ('sessionId', 'session_id', 'thread_id', 'threadId'):
                nested = payload.get(key)
                if nested:
                    return str(nested).strip()
            nested_msg = payload.get('message') if isinstance(payload.get('message'), dict) else None
            if nested_msg:
                nested_sid = str(
                    nested_msg.get('session_id')
                    or nested_msg.get('thread_id')
                    or ''
                ).strip()
                if nested_sid:
                    return nested_sid
        return ''

    def build_loop_history_pointer(
        self,
        project_id: str,
        *,
        correlation_id: str = '',
        focus_cell_ids: list[str] | None = None,
        working_directory: str = '',
        project: dict[str, Any] | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Compact repair-loop pointer for Claude context (no full transcripts)."""
        project_id = str(project_id or '').strip()
        correlation_id = str(correlation_id or '').strip()
        focus = [
            str(item).strip()
            for item in (focus_cell_ids or [])
            if str(item or '').strip()
        ]
        limit = max(1, min(int(limit or 8), 20))
        titles: dict[str, str] = {}
        if isinstance(project, dict):
            for cell in project.get('cells') or []:
                if not isinstance(cell, dict):
                    continue
                cid = str(cell.get('id') or '').strip()
                if cid:
                    titles[cid] = str(cell.get('title') or cell.get('name') or cid).strip() or cid

        repair_commands_used = 0
        reset_at = ''
        with self.lock, self._connect() as connection:
            reset_at = self._loop_reset_at(connection, project_id)
            if correlation_id:
                repair_commands_used = self._count_repair_commands(
                    connection, project_id, correlation_id,
                )

            run_time_filter = 'AND created_at >= ?' if reset_at else ''
            run_time_args: tuple[Any, ...] = (reset_at,) if reset_at else ()

            if correlation_id:
                rows = connection.execute(f'''
                    SELECT run_id, cell_id, correlation_id, status, error, attempt,
                           created_at, started_at, finished_at
                    FROM cell_run
                    WHERE project_id = ? AND correlation_id = ?
                      {run_time_filter}
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (project_id, correlation_id, *run_time_args, limit)).fetchall()
            elif focus:
                placeholders = ','.join('?' for _ in focus)
                rows = connection.execute(f'''
                    SELECT run_id, cell_id, correlation_id, status, error, attempt,
                           created_at, started_at, finished_at
                    FROM cell_run
                    WHERE project_id = ? AND cell_id IN ({placeholders})
                      {run_time_filter}
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (project_id, *focus, *run_time_args, limit)).fetchall()
            else:
                rows = []

            terminal_run_count = 0
            if correlation_id:
                terminal_run_count = int(connection.execute(f'''
                    SELECT COUNT(*) AS count FROM cell_run
                    WHERE project_id = ? AND correlation_id = ?
                      AND status IN ('completed', 'failed', 'stopped', 'interrupted', 'control_protocol_failed')
                      {run_time_filter}
                ''', (project_id, correlation_id, *run_time_args)).fetchone()['count'])

        recent_runs: list[dict[str, Any]] = []
        for row in rows:
            run_id = str(row['run_id'] or '')
            cell_id = str(row['cell_id'] or '')
            error = str(row['error'] or '')
            artifact: dict[str, Any] = {}
            if working_directory and run_id:
                try:
                    from .artifact_store import annotate_artifact_pointer, artifact_paths
                    artifact = annotate_artifact_pointer(
                        artifact_paths(working_directory, run_id).pointer(),
                        working_directory,
                    )
                except (OSError, ValueError):
                    artifact = {
                        'dir': f'.quantflow/artifacts/{run_id}',
                        'manifest_path': f'.quantflow/artifacts/{run_id}/manifest.json',
                        'result_path': f'.quantflow/artifacts/{run_id}/result.json',
                        'error_path': f'.quantflow/artifacts/{run_id}/error.txt',
                        'manifest_exists': False,
                        'result_exists': False,
                        'error_exists': False,
                    }
            recent_runs.append({
                'run_id': run_id,
                'cell_id': cell_id,
                'title': titles.get(cell_id, cell_id),
                'status': row['status'],
                'error_preview': error[:240],
                'attempt': row['attempt'],
                'created_at': row['created_at'],
                'started_at': row['started_at'],
                'finished_at': row['finished_at'],
                'artifact': artifact,
                'inspect_api': f'/quantflow/api/runs/{run_id}' if run_id else '',
            })

        # Chronological for reading; DB returned newest-first.
        recent_runs_chrono = list(reversed(recent_runs))
        # Prefer terminal-run pairs as "rounds"; fall back to repair command count.
        if correlation_id and terminal_run_count > 0:
            loop_round = max(1, (terminal_run_count + 1) // 2)
        else:
            loop_round = max(1, repair_commands_used + 1)
        remaining = max(0, MAX_AUTO_REPAIR_COMMANDS - repair_commands_used)
        return {
            'schema_version': '1',
            'kind': 'loop_history_pointer',
            'project_id': project_id,
            'correlation_id': correlation_id,
            'focus_cell_ids': focus,
            'loop_round': loop_round,
            'repair_commands_used': repair_commands_used,
            'repair_commands_max': MAX_AUTO_REPAIR_COMMANDS,
            'repair_commands_remaining': remaining,
            'terminal_runs_in_correlation': terminal_run_count if correlation_id else len(recent_runs),
            'history_reset_at': reset_at or None,
            'recent_runs': recent_runs_chrono,
            'how_to_inspect': [
                '仅当 artifact.manifest_exists / result_exists 为 true 时才读对应路径（相对 Project 工作目录）。',
                '文件不存在时用 error_preview/status，禁止强读缺失的 manifest.json/result.json。',
                '也可用 GET /quantflow/api/runs/<run_id> 查看该次运行摘要。',
                f'同一 correlation_id 的自动修复配额最多 {MAX_AUTO_REPAIR_COMMANDS} 次（不含 acknowledge / disable_automation）。',
                '若连续失败且 error_preview 同类：换策略、改参，或 disable_automation；不要空转 acknowledge。',
                'UI「重置状态」会清空本指针与修复配额计数。',
            ],
        }

    def _latest_run_resume_fields(self, row: Any) -> dict[str, Any]:
        """Compact fields so UI can offer Claude session resume without another round-trip."""
        out: dict[str, Any] = {
            'has_deliverable': None,
            'claude_session_id': '',
        }
        try:
            result = json.loads(row['result_json'] or '{}')
        except (TypeError, json.JSONDecodeError):
            result = {}
        if not isinstance(result, dict):
            return out
        summary = result.get('summary') if isinstance(result.get('summary'), dict) else {}
        if 'has_deliverable' in summary:
            out['has_deliverable'] = bool(summary.get('has_deliverable'))
        sid = str(
            result.get('session_id')
            or summary.get('claude_session_id')
            or ''
        ).strip()
        if not sid:
            sid = self.get_claude_session_id(str(row['run_id']))
        out['claude_session_id'] = sid
        return out

    def latest_project_cell_runs(self, project_id: str) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute('''
                SELECT r.*, (
                    SELECT transcript.run_id FROM cell_run transcript
                    WHERE transcript.project_id = r.project_id
                      AND transcript.cell_id = r.cell_id
                      AND EXISTS (
                          SELECT 1 FROM run_event event
                          WHERE event.run_id = transcript.run_id
                            AND (
                                json_extract(event.event_json, '$.type') IN (
                                    'output', 'error', 'executor_result', 'artifact', 'claude'
                                )
                                OR json_extract(event.event_json, '$.payload.type') IN (
                                    'assistant', 'user', 'result'
                                )
                            )
                      )
                    ORDER BY transcript.created_at DESC LIMIT 1
                ) AS transcript_run_id
                FROM cell_run r
                JOIN (
                    SELECT cell_id, MAX(created_at) AS latest_created_at
                    FROM cell_run WHERE project_id = ? GROUP BY cell_id
                ) latest ON latest.cell_id = r.cell_id AND latest.latest_created_at = r.created_at
                WHERE r.project_id = ? ORDER BY r.created_at DESC
            ''', (project_id, project_id)).fetchall()
        return [{
            'run_id': row['run_id'], 'cell_id': row['cell_id'], 'status': row['status'],
            'transcript_run_id': row['transcript_run_id'] or row['run_id'],
            'error': row['error'], 'delivery_id': row['delivery_id'],
            'created_at': row['created_at'], 'started_at': row['started_at'],
            'finished_at': row['finished_at'],
            **self._latest_run_resume_fields(row),
        } for row in rows]

    def list_cell_run_ids(self, project_id: str, cell_id: str) -> list[str]:
        """All run ids for a cell, newest first (used by artifact retention)."""
        with self.lock, self._connect() as connection:
            rows = connection.execute('''
                SELECT run_id FROM cell_run
                WHERE project_id = ? AND cell_id = ?
                ORDER BY created_at DESC
            ''', (project_id, cell_id)).fetchall()
        return [str(row['run_id']) for row in rows]

    def latest_completed_cell_run(self, project_id: str, cell_id: str) -> dict[str, Any] | None:
        """Latest completed run for a cell (for data-edge upstream handoff pointers)."""
        project_id = str(project_id or '').strip()
        cell_id = str(cell_id or '').strip()
        if not project_id or not cell_id:
            return None
        with self.lock, self._connect() as connection:
            row = connection.execute('''
                SELECT * FROM cell_run
                WHERE project_id = ? AND cell_id = ? AND status = 'completed'
                ORDER BY created_at DESC
                LIMIT 1
            ''', (project_id, cell_id)).fetchone()
        if not row:
            return None
        return {
            'run_id': row['run_id'], 'project_id': row['project_id'], 'cell_id': row['cell_id'],
            'correlation_id': row['correlation_id'], 'executor_type': row['executor_type'],
            'status': row['status'], 'input': json.loads(row['input_json']),
            'result': json.loads(row['result_json']), 'error': row['error'],
            'attempt': row['attempt'], 'delivery_id': row['delivery_id'],
            'created_at': row['created_at'], 'started_at': row['started_at'],
            'finished_at': row['finished_at'],
        }

    def claim_event_deliveries(self, worker_id: str, limit: int = 20, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=_clamp_lease_seconds(lease_seconds))).isoformat()
        with self.lock, self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute('''
                SELECT d.*, e.event_type, e.source_cell_id, e.source_run_id,
                       e.correlation_id, e.payload_json, e.occurred_at
                FROM event_delivery d JOIN event_log e ON e.event_id = d.event_id
                WHERE (d.status = 'pending' AND (d.next_claim_at IS NULL OR d.next_claim_at <= ?))
                   OR (d.status = 'inflight' AND d.lease_expires_at < ?)
                ORDER BY d.created_at ASC LIMIT ?
            ''', (now.isoformat(), now.isoformat(), max(1, min(limit, 100)))).fetchall()
            claimed = []
            for row in rows:
                cursor = connection.execute('''
                    UPDATE event_delivery SET status = 'inflight', attempt = attempt + 1,
                        lease_owner = ?, lease_expires_at = ?, next_claim_at = NULL, updated_at = ?
                    WHERE delivery_id = ? AND (
                        (status = 'pending' AND (next_claim_at IS NULL OR next_claim_at <= ?))
                        OR (status = 'inflight' AND lease_expires_at < ?)
                    )
                ''', (worker_id, expires, now.isoformat(), row['delivery_id'], now.isoformat(), now.isoformat()))
                if cursor.rowcount:
                    claimed.append({
                        'delivery_id': row['delivery_id'], 'event_id': row['event_id'],
                        'connection_id': row['connection_id'], 'project_id': row['project_id'],
                        'target_cell_id': row['target_cell_id'], 'attempt': row['attempt'] + 1,
                        'event': {
                            'event_id': row['event_id'], 'type': row['event_type'],
                            'source_cell_id': row['source_cell_id'], 'source_run_id': row['source_run_id'],
                            'correlation_id': row['correlation_id'],
                            'payload': json.loads(row['payload_json']), 'occurred_at': row['occurred_at'],
                        },
                    })
            connection.commit()
        return claimed

    def complete_event_delivery(self, delivery_id: str, success: bool, error: str = '', permanent: bool = False) -> None:
        """Finish a claimed delivery.

        - success → acknowledged (no retry).
        - failure → pending with exponential backoff (next_claim_at).
        - attempt >= 5 or ``permanent`` (deterministic failure: target cell
          deleted / not an event cell / tool lacks event support) → deadletter.
        Status guard: a delivery already cancelled (user stop) or deadlettered
        must not be revived by a late runner finalize.
        """
        with self.lock, self._connect() as connection:
            row = connection.execute(
                'SELECT attempt FROM event_delivery WHERE delivery_id = ?', (delivery_id,),
            ).fetchone()
            if not row:
                return
            if success:
                status = 'acknowledged'
                next_claim_at = None
            elif permanent or int(row['attempt']) >= 5:
                status = 'deadletter'
                next_claim_at = None
            else:
                status = 'pending'
                # Exponential backoff: 30s, 60s, 120s, 240s per attempt.
                backoff = min(240, 30 * (2 ** max(0, int(row['attempt']) - 1)))
                next_claim_at = (datetime.now(timezone.utc) + timedelta(seconds=backoff)).isoformat()
            connection.execute('''
                UPDATE event_delivery SET status = ?, lease_owner = NULL,
                    lease_expires_at = NULL, next_claim_at = ?, last_error = ?, updated_at = ?
                WHERE delivery_id = ? AND status IN ('pending', 'inflight')
            ''', (status, next_claim_at, error, _now(), delivery_id))
            connection.commit()

    def defer_event_delivery(self, delivery_id: str, reason: str = '') -> None:
        """Target busy: return to pending and allow an immediate retry."""
        with self.lock, self._connect() as connection:
            connection.execute('''
                UPDATE event_delivery SET status = 'pending', attempt = MAX(attempt - 1, 0),
                    lease_owner = NULL, lease_expires_at = NULL, next_claim_at = NULL,
                    last_error = ?, updated_at = ?
                WHERE delivery_id = ? AND status IN ('pending', 'inflight')
            ''', (reason, _now(), delivery_id))
            connection.commit()

    def cancel_event_delivery(self, delivery_id: str, reason: str = '用户停止，取消事件投递') -> bool:
        """Cancel a single delivery (user stop / flow teardown). Never retried."""
        with self.lock, self._connect() as connection:
            cursor = connection.execute('''
                UPDATE event_delivery SET status = 'cancelled', lease_owner = NULL,
                    lease_expires_at = NULL, next_claim_at = NULL, last_error = ?, updated_at = ?
                WHERE delivery_id = ? AND status IN ('pending', 'inflight')
            ''', (reason, _now(), delivery_id))
            connection.commit()
            return int(cursor.rowcount or 0) > 0

    def retry_event_delivery(self, delivery_id: str) -> bool:
        """Manually re-enqueue a deadlettered/cancelled delivery for immediate retry."""
        with self.lock, self._connect() as connection:
            cursor = connection.execute('''
                UPDATE event_delivery SET status = 'pending', attempt = 0,
                    lease_owner = NULL, lease_expires_at = NULL, next_claim_at = NULL,
                    last_error = '', updated_at = ?
                WHERE delivery_id = ? AND status IN ('deadletter', 'cancelled')
            ''', (_now(), delivery_id))
            connection.commit()
            return int(cursor.rowcount or 0) > 0

    def list_event_deliveries(self, project_id: str, status: str = '', limit: int = 100) -> list[dict[str, Any]]:
        """Delivery ledger for the UI (pending/inflight/deadletter/cancelled)."""
        limit = max(1, min(int(limit or 100), 500))
        allowed = {'pending', 'inflight', 'acknowledged', 'deadletter', 'cancelled'}
        with self.lock, self._connect() as connection:
            if status and status in allowed:
                rows = connection.execute('''
                    SELECT d.*, e.event_type, e.source_cell_id, e.source_run_id,
                           e.correlation_id, e.occurred_at
                    FROM event_delivery d JOIN event_log e ON e.event_id = d.event_id
                    WHERE d.project_id = ? AND d.status = ?
                    ORDER BY d.created_at DESC LIMIT ?
                ''', (project_id, status, limit)).fetchall()
            else:
                rows = connection.execute('''
                    SELECT d.*, e.event_type, e.source_cell_id, e.source_run_id,
                           e.correlation_id, e.occurred_at
                    FROM event_delivery d JOIN event_log e ON e.event_id = d.event_id
                    WHERE d.project_id = ?
                    ORDER BY d.created_at DESC LIMIT ?
                ''', (project_id, limit)).fetchall()
        return [dict(row) for row in rows]

    def cancel_project_event_deliveries(self, project_id: str, reason: str = '用户重置状态') -> int:
        """Cancel pending/inflight event deliveries so old failures do not keep waking cells."""
        with self.lock, self._connect() as connection:
            cursor = connection.execute('''
                UPDATE event_delivery
                SET status = 'cancelled', lease_owner = NULL, lease_expires_at = NULL,
                    next_claim_at = NULL, last_error = ?, updated_at = ?
                WHERE project_id = ? AND status IN ('pending', 'inflight')
            ''', (reason, _now(), project_id))
            connection.commit()
            return int(cursor.rowcount or 0)

    def list_events(self, project_id: str, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self.lock, self._connect() as connection:
            rows = connection.execute('''
                SELECT * FROM event_log WHERE project_id = ?
                ORDER BY occurred_at DESC LIMIT ?
            ''', (project_id, limit)).fetchall()
        return [{
            'event_id': row['event_id'],
            'project_id': row['project_id'],
            'type': row['event_type'],
            'source_cell_id': row['source_cell_id'],
            'source_run_id': row['source_run_id'],
            'correlation_id': row['correlation_id'],
            'causation_id': row['causation_id'],
            'payload': json.loads(row['payload_json']),
            'occurred_at': row['occurred_at'],
        } for row in rows]

    def list_recent_activity(self, limit: int = 24) -> list[dict[str, Any]]:
        """Cheap cross-project activity feed for companion idle chatter."""
        limit = max(1, min(int(limit or 24), 80))
        with self.lock, self._connect() as connection:
            event_rows = connection.execute('''
                SELECT e.event_id, e.project_id, e.event_type, e.source_cell_id,
                       e.source_run_id, e.payload_json, e.occurred_at, p.snapshot_json
                FROM event_log e
                LEFT JOIN project_snapshot p ON p.project_id = e.project_id
                ORDER BY e.occurred_at DESC
                LIMIT ?
            ''', (limit,)).fetchall()
            run_rows = connection.execute('''
                SELECT r.run_id, r.project_id, r.cell_id, r.status, r.error,
                       r.finished_at, r.created_at, p.snapshot_json
                FROM cell_run r
                LEFT JOIN project_snapshot p ON p.project_id = r.project_id
                ORDER BY COALESCE(r.finished_at, r.created_at) DESC
                LIMIT ?
            ''', (limit,)).fetchall()

        def _project_meta(snapshot_json: str | None) -> tuple[str, dict[str, str]]:
            name = '未命名项目'
            titles: dict[str, str] = {}
            if not snapshot_json:
                return name, titles
            try:
                project = json.loads(snapshot_json)
            except json.JSONDecodeError:
                return name, titles
            if not isinstance(project, dict):
                return name, titles
            name = str(project.get('name') or name).strip() or name
            for cell in project.get('cells') or []:
                if not isinstance(cell, dict):
                    continue
                cid = str(cell.get('id') or '').strip()
                if cid:
                    titles[cid] = str(cell.get('title') or cell.get('name') or cid).strip()
            return name, titles

        items: list[dict[str, Any]] = []
        covered_run_ids: set[str] = set()
        for row in event_rows:
            project_name, cell_titles = _project_meta(row['snapshot_json'])
            try:
                payload = json.loads(row['payload_json'] or '{}')
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            summary = payload.get('summary') if isinstance(payload.get('summary'), dict) else {}
            cell_id = str(row['source_cell_id'] or '')
            source_run_id = str(row['source_run_id'] or '').strip()
            # Only cell_run.* events are a duplicate of the cell_run row below;
            # business events (tool.completed, etc.) carry their own meaning.
            if source_run_id and str(row['event_type'] or '').startswith('cell_run'):
                covered_run_ids.add(source_run_id)
            items.append({
                'kind': 'event',
                'key': f"event:{row['event_id']}",
                'project_id': row['project_id'],
                'project_name': project_name,
                'cell_id': cell_id,
                'cell_title': cell_titles.get(cell_id) or cell_id or 'Cell',
                'event_type': row['event_type'],
                'status': str(payload.get('status') or summary.get('status') or ''),
                'error_preview': str(summary.get('error_preview') or payload.get('error') or '')[:120],
                'summary': summary,
                'occurred_at': row['occurred_at'],
            })
        for row in run_rows:
            run_id = str(row['run_id'] or '')
            # Skip runs already represented by an event_log row (same run_id).
            if run_id and run_id in covered_run_ids:
                continue
            project_name, cell_titles = _project_meta(row['snapshot_json'])
            cell_id = str(row['cell_id'] or '')
            items.append({
                'kind': 'run',
                'key': f"run:{run_id}",
                'project_id': row['project_id'],
                'project_name': project_name,
                'cell_id': cell_id,
                'cell_title': cell_titles.get(cell_id) or cell_id or 'Cell',
                'event_type': 'cell_run',
                'status': row['status'],
                'error_preview': str(row['error'] or '')[:120],
                'summary': {},
                'occurred_at': row['finished_at'] or row['created_at'],
            })
        items.sort(key=lambda item: str(item.get('occurred_at') or ''), reverse=True)
        return items[:limit]

    def enqueue_command(self, command: dict[str, Any]) -> dict[str, Any]:
        action = str(command.get('action') or '').strip()
        if action not in ALLOWED_COMMANDS:
            raise ValueError(f'不允许的控制动作: {action}')
        project_id = str(command.get('project_id') or '').strip()
        target_cell_id = str(command.get('target_cell_id') or '').strip()
        if not project_id or not target_cell_id:
            raise ValueError('command.project_id 和 target_cell_id 不能为空')
        now = _now()
        stored = {
            'command_id': str(command.get('command_id') or uuid.uuid4()),
            'project_id': project_id,
            'target_cell_id': target_cell_id,
            'correlation_id': str(command.get('correlation_id') or ''),
            'action': action,
            'expected_revision': command.get('expected_revision'),
            'idempotency_key': str(command.get('idempotency_key') or uuid.uuid4()),
            'reason': str(command.get('reason') or ''),
            'payload': command.get('payload') if isinstance(command.get('payload'), dict) else {},
            'status': 'pending',
            'created_at': now,
            'updated_at': now,
        }
        with self.lock, self._connect() as connection:
            existing = connection.execute('''
                SELECT * FROM command_queue WHERE idempotency_key = ?
            ''', (stored['idempotency_key'],)).fetchone()
            if existing:
                same_command = (
                    existing['project_id'] == stored['project_id'] and
                    existing['target_cell_id'] == stored['target_cell_id'] and
                    existing['correlation_id'] == stored['correlation_id'] and
                    existing['action'] == stored['action'] and
                    existing['expected_revision'] == stored['expected_revision'] and
                    json.loads(existing['payload_json']) == stored['payload']
                )
                if not same_command:
                    raise ValueError('idempotency_key 已用于不同的控制命令')
                return {
                    'command_id': existing['command_id'],
                    'project_id': existing['project_id'],
                    'target_cell_id': existing['target_cell_id'],
                    'correlation_id': existing['correlation_id'],
                    'action': existing['action'],
                    'expected_revision': existing['expected_revision'],
                    'idempotency_key': existing['idempotency_key'],
                    'reason': existing['reason'],
                    'payload': json.loads(existing['payload_json']),
                    'status': existing['status'],
                    'created_at': existing['created_at'],
                    'updated_at': existing['updated_at'],
                    'deduplicated': True,
                }
            connection.execute('''
                INSERT INTO command_queue(
                    command_id, project_id, target_cell_id, correlation_id, action, expected_revision,
                    idempotency_key, reason, payload_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                stored['command_id'], stored['project_id'], stored['target_cell_id'],
                stored['correlation_id'], stored['action'], stored['expected_revision'], stored['idempotency_key'],
                stored['reason'], json.dumps(stored['payload'], ensure_ascii=False),
                stored['status'], stored['created_at'], stored['updated_at'],
            ))
            connection.commit()
        return stored

    def list_commands(self, project_id: str, status: str = 'pending', limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self.lock, self._connect() as connection:
            rows = connection.execute('''
                SELECT * FROM command_queue
                WHERE project_id = ? AND status = ?
                ORDER BY created_at ASC LIMIT ?
            ''', (project_id, status, limit)).fetchall()
        return [{
            'command_id': row['command_id'],
            'project_id': row['project_id'],
            'target_cell_id': row['target_cell_id'],
            'correlation_id': row['correlation_id'],
            'action': row['action'],
            'expected_revision': row['expected_revision'],
            'idempotency_key': row['idempotency_key'],
            'reason': row['reason'],
            'payload': json.loads(row['payload_json']),
            'status': row['status'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
        } for row in rows]

    def update_command_status(self, command_id: str, status: str) -> bool:
        if status not in {'pending', 'running', 'accepted', 'completed', 'failed', 'cancelled', 'forgotten'}:
            raise ValueError(f'不允许的命令状态: {status}')
        with self.lock, self._connect() as connection:
            cursor = connection.execute('''
                UPDATE command_queue SET status = ?, updated_at = ? WHERE command_id = ?
            ''', (status, _now(), command_id))
            connection.commit()
        return cursor.rowcount > 0

    def claim_commands(self, worker_id: str, limit: int = 20, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=_clamp_lease_seconds(lease_seconds))).isoformat()
        with self.lock, self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute('''
                SELECT c.* FROM command_queue c
                LEFT JOIN command_lease l ON l.command_id = c.command_id
                WHERE (c.status = 'pending' OR (c.status = 'running' AND l.lease_expires_at < ?))
                  AND (l.command_id IS NULL OR l.lease_expires_at < ?)
                ORDER BY c.created_at ASC LIMIT ?
            ''', (now.isoformat(), now.isoformat(), max(1, min(limit, 100)))).fetchall()
            claimed = []
            for row in rows:
                connection.execute('''
                    INSERT INTO command_lease(command_id, lease_owner, lease_expires_at, acquired_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(command_id) DO UPDATE SET
                        lease_owner = excluded.lease_owner,
                        lease_expires_at = excluded.lease_expires_at,
                        acquired_at = excluded.acquired_at
                    WHERE command_lease.lease_expires_at < ?
                ''', (row['command_id'], worker_id, expires, now.isoformat(), now.isoformat()))
                lease = connection.execute(
                    'SELECT lease_owner FROM command_lease WHERE command_id = ?', (row['command_id'],),
                ).fetchone()
                if lease and lease['lease_owner'] == worker_id:
                    connection.execute(
                        "UPDATE command_queue SET status='running', updated_at=? WHERE command_id=?",
                        (now.isoformat(), row['command_id']),
                    )
                    claimed.append({
                        'command_id': row['command_id'], 'project_id': row['project_id'],
                        'target_cell_id': row['target_cell_id'], 'action': row['action'],
                        'correlation_id': row['correlation_id'],
                        'expected_revision': row['expected_revision'],
                        'idempotency_key': row['idempotency_key'], 'reason': row['reason'],
                        'payload': json.loads(row['payload_json']),
                    })
            connection.commit()
        return claimed

    def accept_command(self, command_id: str, note: str = '') -> None:
        """Mark a control command as dispatched; effect settles when the target Cell finishes."""
        with self.lock, self._connect() as connection:
            connection.execute(
                '''
                UPDATE command_queue
                SET status = 'accepted',
                    reason = CASE WHEN ? != '' THEN ? ELSE reason END,
                    updated_at = ?
                WHERE command_id = ? AND status IN ('pending', 'running')
                ''',
                (note, note, _now(), command_id),
            )
            connection.execute('DELETE FROM command_lease WHERE command_id = ?', (command_id,))
            connection.commit()

    def finish_command(self, command_id: str, success: bool, error: str = '') -> None:
        status = 'completed' if success else 'failed'
        with self.lock, self._connect() as connection:
            # Do not revive forgotten/cancelled commands after Project reset.
            connection.execute(
                '''
                UPDATE command_queue
                SET status = ?,
                    reason = CASE WHEN ? != '' THEN ? ELSE reason END,
                    updated_at = ?
                WHERE command_id = ? AND status IN ('pending', 'running', 'accepted')
                ''',
                (status, error, error, _now(), command_id),
            )
            connection.execute('DELETE FROM command_lease WHERE command_id = ?', (command_id,))
            connection.commit()

    def defer_command(self, command_id: str, reason: str = '') -> None:
        """Return a claimed command to pending and drop its lease so a later tick can retry."""
        with self.lock, self._connect() as connection:
            connection.execute(
                '''
                UPDATE command_queue
                SET status = ?,
                    reason = CASE WHEN ? != '' THEN ? ELSE reason END,
                    updated_at = ?
                WHERE command_id = ? AND status IN ('pending', 'running', 'accepted')
                ''',
                ('pending', reason, reason, _now(), command_id),
            )
            connection.execute('DELETE FROM command_lease WHERE command_id = ?', (command_id,))
            connection.commit()

    def patch_project_cell(self, project_id: str, cell_id: str, parameters: dict[str, Any], expected_revision: int | None) -> int:
        allowed = {
            'context': 'context', 'goal': 'goal', 'model': 'model',
            'execution_mode': 'executionMode', 'required_toolbox': 'requiredToolbox',
            'forbidden_toolbox': 'forbiddenToolbox', 'trigger_type': 'triggerType',
        }
        snapshot = self.get_project_snapshot(project_id)
        if not snapshot:
            raise ValueError('Project Snapshot 不存在')
        if expected_revision is not None and int(expected_revision) != int(snapshot['revision']):
            raise ValueError('Command expected_revision 已过期')
        project = snapshot['project']
        cell = next((item for item in project.get('cells', []) if str(item.get('id')) == cell_id), None)
        if not cell:
            raise ValueError('目标 Cell 不存在')
        for key, value in parameters.items():
            target = allowed.get(key)
            if target and isinstance(value, str):
                cell[target] = value
        selected_general_tools = parameters.get('selected_general_tools')
        if isinstance(selected_general_tools, list):
            cell['selectedGeneralTools'] = [
                str(item.get('tool_key') if isinstance(item, dict) else item).strip().lower()
                for item in selected_general_tools
                if str(item.get('tool_key') if isinstance(item, dict) else item).strip()
            ]
        forbidden_general_tools = parameters.get('forbidden_general_tools')
        if isinstance(forbidden_general_tools, list):
            cell['forbiddenGeneralTools'] = [
                str(item.get('tool_key') if isinstance(item, dict) else item).strip().lower()
                for item in forbidden_general_tools
                if str(item.get('tool_key') if isinstance(item, dict) else item).strip()
            ]
        selected_scripts = parameters.get('selected_scripts')
        if isinstance(selected_scripts, list):
            cell['selectedScripts'] = [
                str(item.get('type_key') if isinstance(item, dict) else item).strip()
                for item in selected_scripts
                if str(item.get('type_key') if isinstance(item, dict) else item).strip()
            ]
        forbidden_scripts = parameters.get('forbidden_scripts')
        if isinstance(forbidden_scripts, list):
            cell['forbiddenScripts'] = [
                str(item.get('type_key') if isinstance(item, dict) else item).strip()
                for item in forbidden_scripts
                if str(item.get('type_key') if isinstance(item, dict) else item).strip()
            ]
        tool_config = parameters.get('tool_config')
        if isinstance(tool_config, dict):
            executor_config = cell.get('executorConfig')
            if not isinstance(executor_config, dict):
                executor_config = {}
                cell['executorConfig'] = executor_config
            current_tool_config = executor_config.get('tool_config')
            if not isinstance(current_tool_config, dict):
                current_tool_config = {}
            executor_config['tool_config'] = {**current_tool_config, **tool_config}
        if parameters.get('timeout_seconds') is not None:
            from .tool_registry import clamp_tool_timeout_seconds

            executor_config = cell.get('executorConfig')
            if not isinstance(executor_config, dict):
                executor_config = {}
                cell['executorConfig'] = executor_config
            executor_config['timeout_seconds'] = clamp_tool_timeout_seconds(
                parameters.get('timeout_seconds'),
            )
        return self.sync_project(project, expected_revision=snapshot['revision'])

    def get_cell_state(self, project_id: str, cell_id: str) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            row = connection.execute('''
                SELECT revision, state_json, next_run_at, updated_at FROM cell_state
                WHERE project_id = ? AND cell_id = ?
            ''', (project_id, cell_id)).fetchone()
        if not row:
            return {'revision': 0, 'state': {}, 'next_run_at': None, 'updated_at': None}
        return {
            'revision': int(row['revision']),
            'state': json.loads(row['state_json']),
            'next_run_at': row['next_run_at'],
            'updated_at': row['updated_at'],
        }

    def schedule_cell(self, project_id: str, cell_id: str, next_run_at: str | None) -> None:
        with self.lock, self._connect() as connection:
            connection.execute('''
                INSERT INTO cell_state(project_id, cell_id, revision, state_json, next_run_at, updated_at)
                VALUES (?, ?, 0, '{}', ?, ?)
                ON CONFLICT(project_id, cell_id) DO UPDATE SET
                    next_run_at = excluded.next_run_at,
                    updated_at = excluded.updated_at
            ''', (project_id, cell_id, next_run_at, _now()))
            connection.commit()

    def mark_interval_paused(
        self, project_id: str, cell_id: str, reason: str,
        run_id: str = '', status: str = 'failed',
    ) -> dict[str, Any]:
        pause = {
            'paused_at': _now(),
            'reason': str(reason or '周期执行失败，已暂停自动调度'),
            'run_id': str(run_id or ''),
            'status': str(status or 'failed'),
        }
        with self.lock, self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('''
                SELECT revision, state_json FROM cell_state
                WHERE project_id = ? AND cell_id = ?
            ''', (project_id, cell_id)).fetchone()
            state = json.loads(row['state_json']) if row else {}
            revision = int(row['revision']) if row else 0
            state['automation_paused'] = pause
            connection.execute('''
                INSERT INTO cell_state(project_id, cell_id, revision, state_json, next_run_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, ?)
                ON CONFLICT(project_id, cell_id) DO UPDATE SET
                    revision = excluded.revision,
                    state_json = excluded.state_json,
                    next_run_at = NULL,
                    updated_at = excluded.updated_at
            ''', (project_id, cell_id, revision, json.dumps(state, ensure_ascii=False), _now()))
            connection.commit()
        return pause

    def clear_interval_pause(
        self, project_id: str, cell_id: str, next_run_at: str | None = None,
        *,
        extra_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Set next_run_at without touching automation_paused.

        Runner calls this on a completed interval tick to schedule the next run.
        If a user/system pause landed during the run, it stays in place and the
        scheduler's claim guard (claim_scheduled_cell) will refuse to lease the
        cell until resume_interval_cell explicitly clears the pause.
        """
        with self.lock, self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('''
                SELECT revision, state_json, next_run_at FROM cell_state
                WHERE project_id = ? AND cell_id = ?
            ''', (project_id, cell_id)).fetchone()
            state = json.loads(row['state_json']) if row else {}
            revision = int(row['revision']) if row else 0
            if extra_state:
                state.update(extra_state)
            schedule_at = next_run_at if next_run_at is not None else (row['next_run_at'] if row else None)
            connection.execute('''
                INSERT INTO cell_state(project_id, cell_id, revision, state_json, next_run_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, cell_id) DO UPDATE SET
                    revision = excluded.revision,
                    state_json = excluded.state_json,
                    next_run_at = excluded.next_run_at,
                    updated_at = excluded.updated_at
            ''', (
                project_id, cell_id, revision,
                json.dumps(state, ensure_ascii=False), schedule_at, _now(),
            ))
            connection.commit()
        return {
            'revision': revision,
            'state': state,
            'next_run_at': schedule_at,
        }

    def consume_skip_startup_delay(self, project_id: str, cell_id: str) -> bool:
        """Pop and return skip_startup_delay_once from cell state (interval follow-up)."""
        with self.lock, self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('''
                SELECT revision, state_json, next_run_at FROM cell_state
                WHERE project_id = ? AND cell_id = ?
            ''', (project_id, cell_id)).fetchone()
            if not row:
                connection.commit()
                return False
            state = json.loads(row['state_json'] or '{}')
            skip = bool(state.pop('skip_startup_delay_once', False))
            if not skip:
                connection.commit()
                return False
            connection.execute('''
                UPDATE cell_state
                SET state_json = ?, updated_at = ?
                WHERE project_id = ? AND cell_id = ?
            ''', (json.dumps(state, ensure_ascii=False), _now(), project_id, cell_id))
            connection.commit()
        return True

    def resume_interval_cell(self, project_id: str, cell_id: str) -> dict[str, Any]:
        """User-initiated resume: clear automation_paused and arm next_run_at."""
        with self.lock, self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('''
                SELECT revision, state_json FROM cell_state
                WHERE project_id = ? AND cell_id = ?
            ''', (project_id, cell_id)).fetchone()
            state = json.loads(row['state_json']) if row else {}
            revision = int(row['revision']) if row else 0
            state.pop('automation_paused', None)
            # First arm after resume should honor startup_delay_seconds.
            state.pop('skip_startup_delay_once', None)
            schedule_at = _now()
            connection.execute('''
                INSERT INTO cell_state(project_id, cell_id, revision, state_json, next_run_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, cell_id) DO UPDATE SET
                    revision = excluded.revision,
                    state_json = excluded.state_json,
                    next_run_at = excluded.next_run_at,
                    updated_at = excluded.updated_at
            ''', (
                project_id, cell_id, revision,
                json.dumps(state, ensure_ascii=False), schedule_at, _now(),
            ))
            connection.commit()
        return {
            'revision': revision,
            'state': state,
            'next_run_at': schedule_at,
        }

    def pause_interval_cell(
        self, project_id: str, cell_id: str, reason: str = '用户暂停周期调度',
    ) -> dict[str, Any]:
        return self.mark_interval_paused(project_id, cell_id, reason=reason, status='paused')

    def pause_scheduled_intervals(
        self, project_id: str | None = None, reason: str = '服务关闭，已暂停周期调度',
    ) -> int:
        """Pause every interval cell that currently has a next_run_at (actively scheduled)."""
        with self.lock, self._connect() as connection:
            if project_id:
                rows = connection.execute('''
                    SELECT project_id, cell_id FROM cell_state
                    WHERE project_id = ? AND next_run_at IS NOT NULL
                ''', (project_id,)).fetchall()
            else:
                rows = connection.execute('''
                    SELECT project_id, cell_id FROM cell_state
                    WHERE next_run_at IS NOT NULL
                ''').fetchall()
        paused = 0
        for row in rows:
            self.mark_interval_paused(
                row['project_id'], row['cell_id'], reason=reason, status='paused',
            )
            paused += 1
        return paused

    def list_cell_states(self, project_id: str) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute('''
                SELECT cell_id, revision, state_json, next_run_at, updated_at
                FROM cell_state WHERE project_id = ?
            ''', (project_id,)).fetchall()
        results = []
        for row in rows:
            state = json.loads(row['state_json'])
            results.append({
                'cell_id': row['cell_id'],
                'revision': int(row['revision']),
                'state': state,
                'next_run_at': row['next_run_at'],
                'updated_at': row['updated_at'],
                'automation_paused': state.get('automation_paused') if isinstance(state.get('automation_paused'), dict) else None,
            })
        return results

    def claim_scheduled_cell(
        self, project_id: str, cell_id: str, worker_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=_clamp_lease_seconds(lease_seconds))).isoformat()
        with self.lock, self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            state = connection.execute('''
                SELECT revision, state_json, next_run_at FROM cell_state
                WHERE project_id = ? AND cell_id = ?
                  AND next_run_at IS NOT NULL
                  AND next_run_at <= ?
            ''', (project_id, cell_id, now.isoformat())).fetchone()
            if not state:
                connection.commit()
                return None
            state_data = json.loads(state['state_json'] or '{}')
            # Defense in depth: never lease a paused interval cell.
            if isinstance(state_data.get('automation_paused'), dict):
                connection.commit()
                return None
            connection.execute('''
                INSERT INTO schedule_lease(
                    project_id, cell_id, lease_owner, lease_expires_at, acquired_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, cell_id) DO UPDATE SET
                    lease_owner = excluded.lease_owner,
                    lease_expires_at = excluded.lease_expires_at,
                    acquired_at = excluded.acquired_at
                WHERE schedule_lease.lease_expires_at < ?
            ''', (
                project_id, cell_id, worker_id, expires, now.isoformat(), now.isoformat(),
            ))
            lease = connection.execute('''
                SELECT lease_owner FROM schedule_lease
                WHERE project_id = ? AND cell_id = ?
            ''', (project_id, cell_id)).fetchone()
            connection.commit()
        if not lease or lease['lease_owner'] != worker_id:
            return None
        return {
            'revision': int(state['revision']),
            'state': json.loads(state['state_json']),
            'next_run_at': state['next_run_at'],
        }

    def release_schedule_lease(self, project_id: str, cell_id: str, worker_id: str) -> None:
        with self.lock, self._connect() as connection:
            connection.execute('''
                DELETE FROM schedule_lease
                WHERE project_id = ? AND cell_id = ? AND lease_owner = ?
            ''', (project_id, cell_id, worker_id))
            connection.commit()

def _recover_legacy_before_migration(legacy: Path) -> None:
    """Merge any leftover journal/WAL sidecar into the legacy DB before moving it.

    SQLite keeps uncommitted transactions in a sidecar (``-journal`` in DELETE
    mode, ``-wal``/``-shm`` in WAL mode). Moving only the main file would drop
    those trailing events - Cell terminal history would be missing its tail.
    Opening the legacy DB lets SQLite roll the sidecar forward first.
    """
    sidecars = [Path(f'{legacy}-journal'), Path(f'{legacy}-wal'), Path(f'{legacy}-shm')]
    if not any(path.exists() for path in sidecars):
        return
    try:
        connection = sqlite3.connect(str(legacy))
        try:
            connection.execute('PRAGMA journal_mode')
        finally:
            connection.close()
    except sqlite3.Error as exc:
        logging.warning('迁移前恢复旧数据库 %s 失败（将仅迁移主文件）: %s', legacy, exc)


def _find_legacy_store_path(package_file: Path) -> Path | None:
    """Locate a previous install's runtime DB.

    Checks the package directory first (in-place / pip upgrades keep the DB
    there), then a few ancestor levels for copies unzipped into a different
    folder. The newest non-empty match wins; zero-byte crash shells are
    ignored so they can never shadow real data.
    """
    package = Path(package_file).resolve()
    direct = package.with_name('quantflow_control.db')
    if direct.is_file() and direct.stat().st_size > 0:
        return direct
    found: Path | None = None
    found_mtime = 0.0
    for parent in package.parents:
        try:
            candidates = [
                parent / 'quantflow_control.db',
                parent / 'quantflow' / 'quantflow_control.db',
            ]
            # A newer copy unzipped next to the previous install: scan one
            # level of sibling directories for their quantflow/ DB.
            try:
                for child in parent.iterdir():
                    if child.is_dir():
                        candidates.append(child / 'quantflow' / 'quantflow_control.db')
            except OSError:
                pass
            for candidate in candidates:
                if candidate.is_file() and candidate.stat().st_size > 0:
                    mtime = candidate.stat().st_mtime
                    if mtime > found_mtime:
                        found, found_mtime = candidate, mtime
        except OSError:
            continue
        if parent == package.parents[0].anchor:
            break
    return found


def _resolve_store_path(legacy_path: Path | None = None) -> Path:
    """Runtime state lives OUTSIDE the distributable project directory.

    The DB used to sit next to the code, so zipping/redistributing the app
    bundled the owner's machine-local project snapshots - recipients then saw
    projects like D:\\BrainPro that do not exist on their machines. State now
    lives in ~/.quantflow/; a legacy DB next to the code is migrated once.

    Upgrade safety: in-place upgrades find their DB via _find_legacy_store_path
    (package dir first, then ancestor levels), so project records survive.
    """
    legacy = legacy_path if legacy_path is not None else (
        _find_legacy_store_path(Path(__file__)) or Path(__file__).with_name('quantflow_control.db')
    )
    target_dir = Path.home() / '.quantflow'
    # SQLite can create the database file itself, but it cannot create a missing
    # parent directory. Ensure ~/.quantflow exists on first run as well as during
    # legacy database migration.
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / 'quantflow_control.db'
    if legacy.is_file():
        if legacy.stat().st_size == 0:
            # Zero-byte shell (crash residue / file lock artefact): nothing to
            # migrate - remove it so it can never shadow a real database.
            try:
                legacy.unlink()
            except OSError as exc:
                logging.warning('清理空壳数据库 %s 失败: %s', legacy, exc)
        elif target.exists() and target.stat().st_size > 0:
            # Both sides carry data: never overwrite either database. Make the
            # situation visible instead of silently ignoring the old one.
            logging.warning(
                '检测到旧版数据库 %s 与当前数据库 %s 均有数据，未自动覆盖（防止丢失任一库）。'
                '如需恢复旧库数据：停止服务后，用旧库替换 %s 再启动。',
                legacy, target, target,
            )
        else:
            # Target missing, or target is a zero-byte shell: migrate the old
            # database so everything keeps using the new management scheme.
            if target.exists():
                try:
                    target.unlink()
                except OSError as exc:
                    logging.warning('清理空壳目标库 %s 失败: %s', target, exc)
            _recover_legacy_before_migration(legacy)
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(legacy), str(target))
            except OSError as exc:
                logging.warning('迁移旧数据库到 %s 失败: %s', target, exc)
    return target


control_store = ControlStore(_resolve_store_path())