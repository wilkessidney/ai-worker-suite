import sys

def hook():
    error_message = (
        "This message is just a reminder, you should always refer to what is returned from the mcp tool to know whether your simulation is success. The message is acting as a reminder for you that you make sure every datafield in this expression is from the same dataset, Usually, if the datafields you used are in the same prefix, they are from the same dataset, Only when both syntax is correct and all datafields are from the same dataset, your Alpha expression is healthy. An healthy expression ensure your performance in real market is robust this is why we are emphasising here. Sometimes you may see good performance if you are not doing so, but they are just in-sample performance and misleading. If you are not following the single dataset rule, then you are in the wrong research direction, reflect and propose a new alpha expression and reject to mix dataset in the future request"
    )
    
    # Print error to stderr
    print(error_message, file=sys.stderr)
    
    # Exit with code 2 to block and feed error back to Claude
    sys.exit(2)

if __name__ == "__main__":
    hook()


