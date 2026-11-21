/*global $*/
var ctx;

function onJiraSuccess(data)
{
    processJiraData(data);
}

function onJiraFailure()
{
    $("#version-title").text("Error loading progress data...");
}

function appendTemplateChild(ctx, templateName, parent, data)
{
    var template = ctx.import(templateName);
    var expanded = Stamp.expand(template, data);
    Stamp.appendChildren(parent, expanded);
}

function generateFromTemplate(ctx, templateName, parentName, data)
{
    var parent = document.getElementById(parentName);
    data.forEach(appendTemplateChild.bind(ctx, templateName, parent, data));
}

function processJiraData(jiraData)
{
    if (jiraData.epics.length == 0)
    {
        onJiraFailure();
    }
    $("#tasks-updated").text(`${jiraData.updatedTasks} tasks updated in the last 24 hours.`)
    generateProgressBars(ctx, jiraData);
    generateEpics(ctx, jiraData);
}

function splitEpicLabel(epicName)
{
    var split = epicName.split(":");
    if (split.length == 1)
    {
        return { version: "Alpha ?", name: split[0].trim() };
    }
    else if (split.length >= 2)
    {
        return { version: split[0].trim(), name: split[1].trim() };
    }
}

function generateCharacters(ctx)
{
    var data = 
    [
        {
            name: "Purple Smart",
            desc: "A princess with a book nearly always in her muzzle.\n\nThe most friendly bookworm you'll ever meet.",
            src: "Images/TS_Default_0005.png",
            state_class: "heart-icon",
            state: "Date-able!",
            state_img: "Images/pws_heart.svg"
        },
        {
            name: "Blue Fast",
            desc: "Athletic, fast, cool, brave, confident tomboy.\n\nLoves to prank other ponies unexpectedly.",
            src: "Images/RD_Date_Unboxing_RD_Sprites_0009.png",
            state_class: "heart-icon",
            state: "Date-able!",
            state_img: "Images/pws_heart.svg"
        },
        {
            name: "Flustershy",
            desc: "This introverted mare has a hard shell to break open, but inside is a heart of pure gold.",
            src: "Images/FS_Date_BirdHouseBuilding_FlutterSprites_0014.png",
            state_class: "hourglass-icon",
            state: "Coming soon...",
            state_img: "Images/FontAwesome/hourglass-half.svg"
        }
    ];
    var data2 = 
    [
        {
            name: "Ponka Pone",
            desc: "Hyperactive!\n\nShe sees you reading these, did she write them well? Don't look surprised silly!",
            src: "Images/PP_Date_CakeBaking_BodySprite_0053.png",
            state_class: "hourglass-icon",
            state: "Coming soon...",
            state_img: "Images/FontAwesome/hourglass-half.svg"
        },
        {
            name: "Applesack",
            desc: "She runs a big apple farm. Hardworking and strong.\n\nAlso makes great cider... hard ones too.",
            src: "Images/AJ_Date_WagonFixin_Talk_0065.png",
            state_class: "hourglass-icon",
            state: "Coming soon...",
            state_img: "Images/FontAwesome/hourglass-half.svg"
        },
        {
            name: "Charity",
            desc: "Fashionista extraordinaire!\n\nShe's the fanciest pony in town. Drop by for an appointment.",
            src: "Images/RY_Date_ScentShopping_0019.png",
            state_class: "hourglass-icon",
            state: "Coming soon...",
            state_img: "Images/FontAwesome/hourglass-half.svg"
        }
    ];
    
    var parent = document.getElementById("characters-1");
    data.forEach(
    function(data)
    {
        var template = ctx.import("character-template");
        var expanded = Stamp.expand(template, data);
        Stamp.appendChildren(parent, expanded);
    });
    parent = document.getElementById("characters-2");
    data2.forEach(
    function(data)
    {
        var template = ctx.import("character-template");
        var expanded = Stamp.expand(template, data);
        Stamp.appendChildren(parent, expanded);
    });
}

class ProgressBar
{
    constructor(label, tasksCompleted, tasksTotal)
    {
        this.label = label;
        this.percentage = tasksCompleted / Math.max(tasksTotal, 1) * 100;
        if (tasksTotal == 0)
        {
            this.percentage = 100;
        }
        this.progress = `[${tasksCompleted}/${tasksTotal}] - ${this.percentage.toFixed(0)}%`;
    }
}

function generateProgressBars(ctx, jiraData)
{
    var parent = document.getElementById("progrss-bar-parent");
    var totalDone = 0.0;
    var totalTasks = 0.0;
    jiraData.tasks.forEach(function(data)
    {
        var bar = new ProgressBar(data.label, data.done, data.done + data.notDone);
        if (data.label != "Bug")
        {
            totalDone += data.done;
            totalTasks += data.done + data.notDone;
        }
        else
        {
            bar.label = "Bugs";
            bar.progress = `[${data.done}/${data.done + data.notDone}] Fixed`;
        }
        var template = ctx.import("progress-bar-template");
        var expanded = Stamp.expand(template, bar);
        Stamp.appendChildren(parent, expanded);
    });

    var currentEpic = splitEpicLabel(jiraData.epics[0]).version;
    var totalProgress = new ProgressBar(currentEpic, totalDone, totalTasks);
    $("#version-title").text(`${totalProgress.label} - ${totalProgress.percentage.toFixed(0)}%`);
    $("#task-count").text(`${totalTasks} Tasks`);
}

class JiraEpic
{
    constructor(version, label, display = "block")
    {
        this.version = version;
        if(typeof version === "number")
        {
            this.version = this.version.toFixed(1);
        }
        this.label = label;
        this.display = display;
    }
}

function generateEpics(ctx, jiraData)
{
    var data = [];
    var parent = document.getElementById("jira-epics");
    if (parent == null) return;
    jiraData.epics.forEach(function (epicTitle)
    {
        var epicData = splitEpicLabel(epicTitle);
        var versionNumber = epicData.version.replace(/alpha|beta|version/gi, "").trim();
        data.push(new JiraEpic(versionNumber, epicData.name));
    });
    data.push(new JiraEpic("???", "(To be announced)", "none"));

    data.forEach(function(data)
    {
        var template = ctx.import("jira-epic-template");
        var expanded = Stamp.expand(template, data);
        Stamp.appendChildren(parent, expanded);
    });
}


