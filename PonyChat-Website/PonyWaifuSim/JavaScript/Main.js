$(document).ready(function ()
{
    ctx = new Stamp.Context(document);
    generateCharacters(ctx);
    // getJiraInfo(onJiraSuccess, onJiraFailure);  // 已停用：Jira 进度拉取
    getLatestVersionNumber(function (data) { $("#downloads-version-title").text("Alpha " + data) }, function () { })
});