
function getFuncName()
{
    return getFuncName.caller.name
}

function getAspFuncName()
{
    return capitalize(getAspFuncName.caller.name);
}

function capitalize(msg)
{
    return msg.charAt(0).toUpperCase() + msg.slice(1);
}

