/*global $*/

var jiraUri = 'api/jira';
var downloadsUri = 'api/downloads';

var releasesUri = '/api/releases/PonyWaifuSim/versions/latest';

function getDefaultPostMessage(funcName, data, uriStart)
{
    return new Object(
    {
        url: urljoin(uriStart, funcName),
        type: "POST",
        contentType: "application/json; charset=utf-8",
        dataType: "text",
        data: JSON.stringify(data),
        success: function (result) 
        {
            $("#debug").text(result);
        },
        error: function (result) 
        {
            $("#debug").text(result);
        }
    });
}

function defaultGetMessage(funcName, uriStart, onGet)
{
    $.get(urljoin(uriStart, funcName), onGet);
}

function getJiraInfo(onSuccess, onFailure)
{
    var message = defaultGetMessage(getAspFuncName(), jiraUri,
        function onResult(data, status, xhr)
        {
            if (status == "success")
            {
                onSuccess(data);
            }
            else
            {
                onFailure();
            }
        });
}

function getLatestVersionNumber(onSuccess, onFailure)
{
    var message = defaultGetMessage(releasesUri, 'https://backend.studiowhy.net',
        function onResult(data, status, xhr)
        {
            if (status == "success")
            {
                onSuccess(data);
            }
            else
            {
                onFailure();
            }
        });
}
