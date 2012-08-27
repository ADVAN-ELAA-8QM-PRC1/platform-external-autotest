var USBLoaded = '<span class="goofy-label-en">LOADED</span>' +
    '<span class="goofy-label-zh">已載入</span>';
var USBUnloaded = '<span class="goofy-label-en">UNLOADED</span>' +
    '<span class="goofy-label-zh">未載入</span>';
var fxtAvailable = '<span class="goofy-label-en">OK</span>' +
    '<span class="goofy-label-zh">已連接</span>';
var fxtUnavailable = '<span class="goofy-label-en">UNAVAILABLE</span>' +
    '<span class="goofy-label-zh">未連接</span>';
var fxtDetecting = '<span class="goofy-label-en">DETECTING</span>' +
    '<span class="goofy-label-zh">偵測中</span>';
var statIdle = '<span class="color_idle goofy-label-en">IDLE</span>' +
    '<span class="color_idle goofy-label-zh">閒置中</span>';

window.onkeydown = function(event) {
    if (event.keyCode == 13 || event.keyCode == 32) {
        var testButton = document.getElementById("btn_run_test");
        if (!testButton.disabled)
            ButtonRunTestClick();
    }
}

function InitLayout(testFull) {
    if (testFull) {
        document.getElementById("test_sn_label").hidden = true;
        document.getElementById("test_sn").hidden = true;
        document.getElementById("menu_placeholder").style.height = "30%";
    } else {
        var snInputBox = document.getElementById("serial_number");
        snInputBox.disabled = false;
        snInputBox.autofocus = true;
    }
}

function UpdateTestBottonStatus() {
    var testButton = document.getElementById("btn_run_test");
    var isSnReady = (document.getElementById("test_sn").hidden ||
                     document.getElementById("serial_number").value !== "");
    testButton.disabled =
        !(isSnReady &&
        document.getElementById('serial_number').validity.valid &&
        document.getElementById('usb_status').innerHTML == USBLoaded &&
        document.getElementById('fixture_status').innerHTML == fxtAvailable);
}

function OnSnInputBoxClick() {
    var snInputBox = document.getElementById("serial_number");
    snInputBox.value="";
    UpdateTestBottonStatus();
}

function OnUSBInsertion() {
    document.getElementById("usb_status").innerHTML = USBLoaded;
    document.getElementById("test_param").className = "panel_good";
    UpdateTestBottonStatus();
}

function OnUSBInit(pattern) {
    document.getElementById("prompt_usb").hidden = true;
    document.getElementById("container").hidden = false;
    document.getElementById("usb_status").innerHTML = USBLoaded;
    document.getElementById("test_param").className = "panel_good";
    ConfigureSNInputbox(pattern);
    test.sendTestEvent('sync_fixture', {});
}

function OnUSBRemoval() {
    document.getElementById("usb_status").innerHTML = USBUnloaded;
    document.getElementById("test_param").className = "panel_bad";
    UpdateTestBottonStatus();
}

function ConfigureSNInputbox(pattern) {
    var snInputBox = document.getElementById("serial_number");
    if (!snInputBox.disabled) {
        snInputBox.pattern = pattern;
        snInputBox.focus();
    }
}

function OnAddFixtureConnection() {
    document.getElementById("fixture_status").innerHTML = fxtAvailable;
    document.getElementById("test_fixture").className = "panel_good";
    UpdateTestBottonStatus();
}

function OnRemoveFixtureConnection() {
    document.getElementById("fixture_status").innerHTML = fxtUnavailable;
    document.getElementById("test_fixture").className = "panel_bad";
    UpdateTestBottonStatus();
}

function OnDetectFixtureConnection() {
    document.getElementById("fixture_status").innerHTML = fxtDetecting;
    document.getElementById("test_fixture").className = "panel_bad";
    UpdateTestBottonStatus();
}

function ButtonRunTestClick() {
    var testButton = document.getElementById("btn_run_test");
    testButton.disabled = true;
    test.sendTestEvent("run_test",
        {"sn": document.getElementById("serial_number").value});
    testButton.disabled = false;
    UpdateTestBottonStatus();
}

function ButtonExitTestClick() {
    test.sendTestEvent("exit_test", {});
}

function ResetUiData() {
    document.getElementById("camera_image").hidden = true;
    document.getElementById("camera_image").src = "";
    document.getElementById("analyzed_image").hidden = true;
    document.getElementById("analyzed_image").src = "";
    UpdateTestStatus(statIdle);
    UpdatePrograssBar("0%");
}

function ClearBuffer() {
    buf = ""
}

function AddBuffer(value) {
    buf += value
}

function UpdateImage(container_id) {
    var img = document.getElementById(container_id);
    img.src = "data:image/jpeg;base64," + buf;
    img.hidden = false;
}

function UpdateTestStatus(msg) {
    var statusText = document.getElementById("test_status");
    statusText.innerHTML = msg;
}

function UpdatePrograssBar(progress) {
    var pBar = document.getElementById("progress_bar");
    pBar.style.width = progress;
}
