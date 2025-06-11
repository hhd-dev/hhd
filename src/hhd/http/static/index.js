async function fetchSettings() {
    // Replace this URL with your actual API endpoint
    const response = await fetch('/api/v1/settings');
    if (!response.ok) {
        throw new Error('Failed to fetch settings');
    }
    return await response.json();
}

function createInputForSetting(setting) {
    let input;

    switch (setting.type) {
        case 'bool':
            input = document.createElement('input');
            input.type = 'checkbox';
            input.checked = setting.default;
            break;
        case 'int':
            input = document.createElement('input');
            input.type = 'number';
            input.value = setting.default;
            input.min = setting.min;
            input.max = setting.max;
            break;
        case 'discrete':
            input = document.createElement('select');
            setting.options.forEach(option => {
                const optionElement = document.createElement('option');
                optionElement.value = option;
                optionElement.textContent = option;
                optionElement.selected = option === setting.default;
                input.appendChild(optionElement);
            });
            break;
        case 'multiple':
            input = document.createElement('select');
            Object.entries(setting.options).forEach(([key, value]) => {
                const optionElement = document.createElement('option');
                optionElement.value = key;
                optionElement.textContent = value;
                optionElement.selected = key === setting.default;
                input.appendChild(optionElement);
            });
            break;
        // Add other cases as needed
    }

    return input;
}

function createFormSection(children, containerId) {
    const sectionContainer = document.createElement('div');
    sectionContainer.id = containerId;

    Object.entries(children).forEach(([key, setting]) => {
        // Ensure each setting is processed correctly
        if (!setting || typeof setting !== 'object') {
            console.log(`Skipping invalid setting: ${key}`);
            return; // Skip invalid settings
        }

        const label = document.createElement('label');
        label.htmlFor = key;
        label.textContent = setting.title;

        const input = createInputForSetting(setting);
        if (!input) {
            console.log(`Input not created for setting: ${key}`);
            return; // Skip settings for which input could not be created
        }

        const div = document.createElement('div');
        div.appendChild(label);
        div.appendChild(input);
        sectionContainer.appendChild(div);
    });

    return sectionContainer;
}


async function loadSettings() {
    try {
        const settings = await fetchSettings();

        // Assuming 'settings' contains 'hhd' and 'controllers' keys at root level
        if (settings.hhd && settings.hhd.http && settings.hhd.http.children) {
            console.log('HHD HTTP children:', settings.hhd.http.children);
            const hhdSectionForm = createFormSection(settings.hhd.http.children, 'hhd-http-form');
            document.getElementById('settingsContainer').appendChild(hhdSectionForm);
        } else {
            console.log('No children present in HHD HTTP settings');
        }

        if (settings.controllers && settings.controllers.legion_go && settings.controllers.legion_go.children) {
            const controllersSectionForm = createFormSection(settings.controllers.legion_go.children, 'controllers-legion-go-form');
            if (controllersSectionForm) {
                document.getElementById('settingsContainer').appendChild(controllersSectionForm);
            } else {
                console.log('Form section for Controllers Legion Go is not valid');
            }
        } else {
            console.log('No children present in Controllers Legion Go settings');
        }
    } catch (error) {
        console.error('Error loading settings:', error);
    }
}


// Call loadSettings when the document is ready
document.addEventListener('DOMContentLoaded', loadSettings);
