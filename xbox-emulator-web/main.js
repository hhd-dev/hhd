// Simple navigation logic for sections
document.querySelectorAll('nav a').forEach(link => {
  link.addEventListener('click', function (e) {
    e.preventDefault();
    document.querySelectorAll('nav a').forEach(a => a.classList.remove('active'));
    this.classList.add('active');
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelector(this.getAttribute('href')).classList.add('active');
    // Hide emulator overlay if navigating
    document.getElementById('emulator-controls').style.display = 'none';
  });
});

// Placeholder: file upload (ROM import)
document.getElementById('file-upload').addEventListener('change', function () {
  alert('ROM upload feature coming soon!');
});

// Emulator controls overlay toggling (demo)
document.querySelectorAll('.play-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.getElementById('emulator-controls').style.display = 'block';
    // Show SX emulator bar if SX mode is enabled
    if(document.body.classList.contains('sx-mode')) {
      document.getElementById('sx-emulator-bar').style.display = 'flex';
    } else {
      document.getElementById('sx-emulator-bar').style.display = 'none';
    }
  });
});
document.getElementById('close-emulator').addEventListener('click', () => {
  document.getElementById('emulator-controls').style.display = 'none';
});

// Controller detection and testing
const controllerConnection = document.getElementById('controller-connection');
const controllerDetails = document.getElementById('controller-details');
const controllerList = document.getElementById('controller-list');
const buttonGrid = document.getElementById('button-grid');
const axisGrid = document.getElementById('axis-grid');

let lastGamepadStates = {};

function updateControllerStatus() {
  const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
  const connectedGamepads = [];
  for (let i = 0; i < gamepads.length; i++) {
    let gp = gamepads[i];
    if (gp && gp.connected) connectedGamepads.push(gp);
  }
  // Update status text
  if (connectedGamepads.length > 0) {
    controllerConnection.textContent = "Connected";
    controllerDetails.style.display = "block";
    controllerList.innerHTML = '';
    connectedGamepads.forEach((gp, idx) => {
      let li = document.createElement('li');
      li.textContent = `${gp.id} (Index: ${gp.index})`;
      controllerList.appendChild(li);
    });
    // Show button and axis testers for first controller
    showButtonTester(connectedGamepads[0]);
    showAxisTester(connectedGamepads[0]);
  } else {
    controllerConnection.textContent = "Not Connected";
    controllerDetails.style.display = "none";
    buttonGrid.innerHTML = '';
    axisGrid.innerHTML = '';
  }
}

function showButtonTester(gp) {
  buttonGrid.innerHTML = '';
  gp.buttons.forEach((btn, idx) => {
    const btnEl = document.createElement('button');
    btnEl.className = "controller-btn";
    btnEl.textContent = idx;
    if (btn.pressed) btnEl.classList.add('active');
    btnEl.title = `Button ${idx}`;
    buttonGrid.appendChild(btnEl);
  });
}

function showAxisTester(gp) {
  axisGrid.innerHTML = '';
  gp.axes.forEach((val, idx) => {
    const axisRow = document.createElement('div');
    axisRow.className = 'axis-bar';
    axisRow.title = `Axis ${idx}: ${val.toFixed(2)}`;
    // Axis indicator (centered, -1 to +1)
    const indicator = document.createElement('div');
    indicator.className = 'axis-indicator';
    indicator.style.left = `${((val + 1) / 2) * 100}%`;
    indicator.style.width = '8px';
    axisRow.appendChild(indicator);
    // Label
    const label = document.createElement('span');
    label.style.position = 'absolute';
    label.style.left = '8px';
    label.style.top = '14px';
    label.style.fontSize = '0.95em';
    label.style.color = '#fff9';
    label.textContent = `Axis ${idx}: ${val.toFixed(2)}`;
    axisRow.appendChild(label);
    axisGrid.appendChild(axisRow);
  });
}

// Poll for gamepad status and button/axis
function pollGamepads() {
  const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
  let changed = false;
  for (let i = 0; i < gamepads.length; i++) {
    let gp = gamepads[i];
    if (gp && gp.connected) {
      // Check if button or axis state changed
      let last = lastGamepadStates[gp.index];
      if (!last || JSON.stringify(last.buttons) !== JSON.stringify(gp.buttons.map(b => b.pressed))
        || JSON.stringify(last.axes) !== JSON.stringify(gp.axes)) {
        changed = true;
        lastGamepadStates[gp.index] = {
          buttons: gp.buttons.map(b => b.pressed),
          axes: Array.from(gp.axes)
        };
      }
    }
  }
  if (changed) updateControllerStatus();
}

window.addEventListener("gamepadconnected", updateControllerStatus);
window.addEventListener("gamepaddisconnected", updateControllerStatus);
setInterval(() => {
  pollGamepads();
}, 150);

// Initial call
updateControllerStatus();

// SX MODE TOGGLE LOGIC
const sxToggle = document.getElementById('sx-mode-toggle');
const sxBanner = document.getElementById('sx-banner');
const mainLogo = document.getElementById('main-logo');

if (sxToggle) {
  // Restore from localStorage if previously set
  if (localStorage.getItem('sxMode') === 'on') {
    document.body.classList.add('sx-mode');
    if(sxBanner) sxBanner.style.display = 'flex';
    sxToggle.checked = true;
    if (mainLogo) mainLogo.src = "xbox360-logo.svg";
  }
  sxToggle.addEventListener('change', function() {
    if (sxToggle.checked) {
      document.body.classList.add('sx-mode');
      if(sxBanner) sxBanner.style.display = 'flex';
      localStorage.setItem('sxMode', 'on');
      if (mainLogo) mainLogo.src = "xbox360-logo.svg";
      if(document.getElementById('emulator-controls').style.display === 'block') {
        document.getElementById('sx-emulator-bar').style.display = 'flex';
      }
    } else {
      document.body.classList.remove('sx-mode');
      if(sxBanner) sxBanner.style.display = 'none';
      localStorage.setItem('sxMode', 'off');
      if (mainLogo) mainLogo.src = "xbox-logo.svg";
      document.getElementById('sx-emulator-bar').style.display = 'none';
    }
  });
}