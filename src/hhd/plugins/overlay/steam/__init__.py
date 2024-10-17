# import os

# def get_game_data(appcache: str):from hhd.plugins.overlay.steam import appcache
import os

from .appcache import parse_appinfo

def get_games(appdir: str):
    with open(os.path.join(appdir, "appinfo.vdf"), 'rb') as f:
        games = {}
        _, data = parse_appinfo(f)
        for d in data:
            try:
                appid = str(d['appid'])
                name = d['data']['appinfo']['common']['name']
                games[appid] = {"name": name, "images": []}
            except KeyError:
                pass
    
    images = {}
    libdir = os.path.join(appdir, "librarycache")
    for fn in os.listdir(libdir):
        try:
            id_split = fn.index('_')
            ext_split = fn.rindex('.')
            appid = fn[:id_split]
            itype = fn[id_split+1:ext_split]

            if appid not in games:
                continue

            games[appid]["images"].append(itype)

            if appid not in images:
                images[appid] = {}

            images[appid][itype] = os.path.join(libdir, fn)
        except ValueError:
            pass
    
    return games, images