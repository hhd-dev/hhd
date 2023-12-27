# HTTP API Docs (v1)
HHD now has a simple and fully featured HTTP endpoint, which allows configuring
all available settings.
All endpoints below should be prefixed with `/api/v1/`.

## Authentication
By default, the endpoint is restricted to localhost, and is only available through
the use of a token.
This token is automatically generated in `~/.config/hhd/token` and can be changed
afterwards by the user as well.

The authentication is achieved through HTTP basic auth with a bearer token.
This means that all requests to `/api/v1` require the header `Authorization`
with content `Bearer <token>`.

To retrieve the user, you can either ask the user for it (they can retrieve it
with `hhd token`), or read it from `~/.config/hhd/token` with either superuser 
or that user's permissions.

## Settings endpoint (`./api/v1/settings`)
The API is on purpose very simple.
The settings endpoint `settings` returns the currently available settings as a
JSON.
All the available settings types can be found in `src/hhd/plugins.py`.
HHD ensures the json will have all the listed values in plugins.py, so you
may not check if they exist.

Each setting has a title which is meant to be shown in the UI and an optional 
hint meant to be shown under a hover hint or `?` button.

Each setting may include tags, which work like classes. 
For example, a keyboard mapping setting may have the tags 
`[razer_lycosa_123, razer_kbd, keyboard, advanced]`, which would allow the UI
to customize the presentation based on the specific device make, manufacturer,
or if neither are supported, show a generic keyboard remapper.
Tags are ordered by specificity, so `razer_lycosa_123` overrides `razer_kbd`.
The tag `advanced` can be used as a hint to hide the setting in simplified UIs (TBD).

Essentially, under the type `Settings` are all the available settings, which
are self explanatory.
- `event`: Meant to simulate a one off event, like a reset. Set to true and hhd will remove it once it's applied (unused).
- `bool`: Checkbox setting
- `multiple`: Radial/dropdown setting. Options is a dictionary of values to UI friendly titles.
- `discrete`: Allows a number of fixed integer or floating values 
  (options is listed in increasing order). You may handle the same as multiple.
- `float`: Floating point setting, with optional min, max values
- `int`: Integer setting, same as above
- `color`: Broken and unused right now

Each setting can be set to a single value coherent for its type (except color, tbd).

Settings are grouped within containers with a type `container`, which has
an ordered dictionary of children.
The key of the dictionary is the id that will be used for the option.
Containers can be nested within containers, and the id of each container is 
appended to the option name.

HHD features settings sections, which are the outermost layer.
This allows you to only focus at the settings necessary for each UI component
(TDP, controllers, hhd settings).

Here is an example that you will receive in json form from `/settings` (in yaml):
```yaml
version: <hex>
hhd:
    http:
        type: container
        tags: [hhd-http]
        title: REST API Configuration (BETA)
        hint: >-
            Settings for configuring the http endpoint of HHD.

        children:
            enable:
            type: bool
            title: Enable REST API.
            hint: >-
                Enables the rest API of Handheld Daemon
            default: False
            port:
            type: int
            title: REST API Port
            hint: >-
                Which port should the REST API be on?
            min: 1024
            max: 49151
            default: 5335
```

The example above will result in the following default state:
```yaml
hhd:
    http:
        enable: False
        port: 5335
```

Settings can be viewed both as nested dictionaries and as a single dictionary.
The following states are identical according to HHD.
```yaml
hhd.http:
    enable: False
    port: 5335
```
```yaml
hhd.http.enable: False
hhd.http.port: 5335
```
```yaml
hhd:
    http:
        enable: False
hhd.http.port: 5335
```

You also receive a version hex, which contains whether the settings have changed
and would prompt you to redraw your UI.
Currently, HHD settings do not change after service start, but future plugins
that rely on autodetection may start when e.g., a controller is connected.
This will make the settings change.

HHD always performs validation for the currently loaded settings, so using a stale
state will not create problems.

The final setting type is `mode`, which is a special type of container.
It is meant to be displayed as an accordion, with a specific sub-container
shown at a time.

```yaml
controllers.legion_go:
    type: container
    tags: [lgc]
    title: Legion Controllers Configuration
    # ...

    children:
    xinput:
        type: mode
        # ...

        default: ds5e
        modes:
        disabled:
            type: container
            # ...

            children:
            shortcuts:
                # ...
        ds5e:
            type: container
            # ...

            children:
            led_support:
                # ...
```

The above will create the following default state:
```yaml
controllers.legion_go.xinput.mode: ds5e
controllers.legion_go.xinput.disabled.shortcuts: disabled
controllers.legion_go.xinput.ds5e.led_support: True
```

Example call (token disabled):
```bash
curl -i http://localhost:5335/api/v1/settings
HTTP/1.0 200 OK
Server: BaseHTTP/0.6 Python/3.11.6
Date: ...
Access-Control-Allow-Origin: *
Access-Control-Allow-Credentials: true
WWW-Authenticate: Bearer

{"controllers": {"legion_go": ...
```

## State endpoint (`./api/v1/state`)
The state endpoint with `GET` returns the current app state in JSON form.
Currently, only the nested dictionary form is returned, e.g.:
```yaml
hhd:
    http:
        enable: False
        port: 5335
```
However, a future option will allow returning a single dictionary:
```yaml
hhd.http.enable: False
hhd.http.port: 5335
```

You can also `POST` to the same endpoint with a mixed state presentation, which
may include some options inlined and some as nested dictionaries.
You only need to send changed options and HHD will merge them to the current
state internally.

The `POST` endpoint will lock, apply the settings under `HHD`, and will return
the updated state.

> Warning: the post endpoint may lock for up to 5+ seconds. 
> Use a separate fetch thread/promise!
> Typically, it will be much less than 1 second.

Example call (token disabled):
```bash
curl -i http://localhost:5335/api/v1/state
HTTP/1.0 200 OK
Server: BaseHTTP/0.6 Python/3.11.6
Date: ...
Access-Control-Allow-Origin: *
Access-Control-Allow-Credentials: true
WWW-Authenticate: Bearer

{"controllers": {"legion_go": {"xinput": {"mode": "ds5e", "disabled": {"shortcuts": true}, "ds5e": {"led_support": true}}, "gyro": true, "accel": true, "gyro_fix": 100, "swap_legion": "disabled", "share_to_qam": true, "touchpad_mode": "crop_end", "debug": false, "shortcuts": true}}, "hhd": {"http": {"enable": true, "port": 5335, "localhost": true, "token": false}}, "version": "af6eb199"}%
```

## Profile endpoint
HHD contains a profile system for changing multiple settings at a time.
This can be done per game, when switching windows, etc.

The `profile` endpoint has 4 sub-endpoints: `list`, `apply`, `get`, `set`, `del`.

Only characters and spaces are supported for the profile name.
HHD will silently strip other characters from the name.

### `profile/list` Endpoint
The `list` `GET` endpoint returns a list of the available profiles.

```bash
curl -i http://localhost:5335/api/v1/profile/list
HTTP/1.0 200 OK
Server: BaseHTTP/0.6 Python/3.11.6
Date: ...
Access-Control-Allow-Origin: *
Access-Control-Allow-Credentials: true
WWW-Authenticate: Bearer

["test"]%  
```

### `profile/apply` Endpoint
The `apply` `GET` endpoint applies the selected profiles in the specified order
and returns the new HHD state.
The applied profiles are supplied as query arguments.
You may apply multiple profiles at a time, by nesting them as query parameters.
```bash
curl -i http://localhost:5335/api/v1/profile/apply\?profile\=\&profile\=test2
HTTP/1.0 200 OK
Server: BaseHTTP/0.6 Python/3.11.6
Date: ...
Access-Control-Allow-Origin: *
Access-Control-Allow-Credentials: true
WWW-Authenticate: Bearer

{"controllers": {"legion_go": {"xinput": {"mode": "ds5e", "disabled": {"shortcuts": true}, "ds5e": {"led_support": true}}, "gyro": true, "accel": true, "gyro_fix": 100, "swap_legion": "disabled", "share_to_qam": true, "touchpad_mode": "crop_end", "debug": false, "shortcuts": true}}, "hhd": {"http": {"enable": true, "port": 5335, "localhost": true, "token": false}}, "version": "af6eb199"}% 
```

### `profile/set` Endpoint
The set endpoint allows you to update the contents of a profile.
The response contains the updated profile.
The `set` endpoint replaces the whole profile and validates it, unlike the state
endpoint which merges it to the current state.
```bash
curl -i -X POST -d '{"controllers.legion_go.shortcuts": false}' http://localhost:5335/api/v1/profile/set\?profile\=test
HTTP/1.0 200 OK
Server: BaseHTTP/0.6 Python/3.11.6
Date: ...
Access-Control-Allow-Origin: *
Access-Control-Allow-Credentials: true
WWW-Authenticate: Bearer

{"controllers": {"legion_go": {"shortcuts": false}}, "version": "af6eb199"}% 
```

### `profile/get` Endpoint
The `get` `GET` endpoint allows you to retrieve the contents of a profile.
```bash
curl -i http://localhost:5335/api/v1/profile/get\?profile\=test
HTTP/1.0 200 OK
Server: BaseHTTP/0.6 Python/3.11.6
Date: ...
Access-Control-Allow-Origin: *
Access-Control-Allow-Credentials: true
WWW-Authenticate: Bearer

{"controllers": {"legion_go": {"shortcuts": false}}, "version": "af6eb199"}%   
```

### `profile/del` Endpoint
The `del` `GET` endpoint deletes the provided profile.

```bash
# Profile exists
curl -i http://localhost:5335/api/v1/profile/del\?profile\=test
HTTP/1.0 200 OK
Server: BaseHTTP/0.6 Python/3.11.6
Date: ...
Access-Control-Allow-Origin: *
Access-Control-Allow-Credentials: true
WWW-Authenticate: Bearer

# Profile does not exist
curl -i http://localhost:5335/api/v1/profile/del\?profile\=test
HTTP/1.0 400 Bad Request
Server: BaseHTTP/0.6 Python/3.11.6
Date: ...
Access-Control-Allow-Origin: *
Access-Control-Allow-Credentials: true
WWW-Authenticate: Bearer
Content-type: text / plain

Handheld Daemon Error:
Profile 'test' not found.% 
```

## Handling Errors
The `v1` API will always return a `JSON` object with status code 200 if called properly.

When called improperly, it will return the following status codes:
  - 401: Unauthorized: your token is invalid.
  - 404: The endpoint you tried to access does not exist.
  - 400: You supplied invalid parameters.

The content of the response will be a human readable explanation in text form.
You may choose to display that to the user, through a modal or portal.

## Version endpoint
You can query the version of the HHD V1 API to determine which features are available
and whether the user should update either your app or HHD.
The version is 1 now and this endpoint requires authentication.
It might not require authentication in the future.
```bash
curl -i http://localhost:5335/api/v1/version
HTTP/1.0 200 OK
Server: BaseHTTP/0.6 Python/3.11.6
Date: ...
Access-Control-Allow-Origin: *
Access-Control-Allow-Credentials: true
WWW-Authenticate: Bearer

{"version": 1}% 
```