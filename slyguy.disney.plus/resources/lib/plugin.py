import random

from kodi_six import xbmcplugin

from slyguy import plugin, gui, userdata, signals, inputstream, settings
from slyguy.log import log
from slyguy.exceptions import PluginError
from slyguy.constants import KODI_VERSION

from .api import API
from .language import _
from .constants import PAGE_SIZE

api = API()

@signals.on(signals.BEFORE_DISPATCH)
def before_dispatch():
    api.new_session()
    plugin.logged_in = api.logged_in

@plugin.route('')
def index(**kwargs):
    folder = plugin.Folder(cacheToDisc=False)

    if not api.logged_in:
        folder.add_item(label=_(_.LOGIN, _bold=True),  path=plugin.url_for(login))
    else:
        folder.add_item(label=_(_.FEATURED, _bold=True), path=plugin.url_for(collection, slug='home', content_class='home', label=_.FEATURED))
        folder.add_item(label=_(_.MOVIES, _bold=True),  path=plugin.url_for(collection, slug='movies', content_class='contentType'))
        folder.add_item(label=_(_.SERIES, _bold=True),  path=plugin.url_for(collection, slug='series', content_class='contentType'))
        folder.add_item(label=_(_.ORIGINALS, _bold=True),  path=plugin.url_for(collection, slug='originals', content_class='originals'))
       # folder.add_item(label=_(_.COLLECTIONS, _bold=True),  path=plugin.url_for(collection, slug='explore', content_class='explore'))
        folder.add_item(label=_(_.WATCHLIST, _bold=True),  path=plugin.url_for(collection, slug='watchlist', content_class='watchlist'))
        folder.add_item(label=_(_.SEARCH, _bold=True),  path=plugin.url_for(search))

        if not userdata.get('kid_lockdown', False):
            folder.add_item(label=_.SELECT_PROFILE, path=plugin.url_for(select_profile), art={'thumb': userdata.get('avatar')}, info={'plot': userdata.get('profile')})

        folder.add_item(label=_.LOGOUT, path=plugin.url_for(logout))
    
    folder.add_item(label=_.SETTINGS, path=plugin.url_for(plugin.ROUTE_SETTINGS))

    return folder

@plugin.route()
def login(**kwargs):
    username = gui.input(_.ASK_USERNAME, default=userdata.get('username', '')).strip()
    if not username:
        return

    userdata.set('username', username)

    password = gui.input(_.ASK_PASSWORD, hide_input=True).strip()
    if not password:
        return

    api.login(username, password)
    _select_profile()
    gui.refresh()

@plugin.route()
def select_profile(**kwargs):
    if userdata.get('kid_lockdown', False):
        return
        
    _select_profile()
    gui.refresh()

def _avatars():
    avatars = {}

    data = api.collection_by_slug(slug='avatars', content_class='avatars')
    for row in data['containers']:
        for item in row['set'].get('items', []):
            avatars[item['avatarId']] = item['images'][0]['url']

    return avatars

def _select_profile():
    profiles = api.profiles()
    active   = api.active_profile()
    avatars  = _avatars()

    options = []
    values  = []
    used_avatars = []
    can_delete = []
    default = -1
    
    for index, profile in enumerate(profiles):
        options.append(profile['profileName'])
        values.append(profile)
        used_avatars.append(profile['attributes']['avatar']['id'])

        profile['_avatar'] = avatars.get(profile['attributes']['avatar']['id'])

        if profile['profileId'] == active.get('profileId'):
            default = index

            userdata.set('avatar', profile['_avatar'])
            userdata.set('profile', profile['profileName'])

        if not profile['attributes']['isDefault']:
            can_delete.append(profile)

    options.append(_(_.ADD_PROFILE, _bold=True))
    values.append('_add')

    if can_delete:
        options.append(_(_.DELETE_PROFILE, _bold=True))
        values.append('_delete')

    index = gui.select(_.SELECT_PROFILE, options=options, preselect=default)

    if index < 0:
        return

    selected = values[index]

    if selected == '_delete':
        _delete_profile(can_delete)
        return _select_profile()

    elif selected == '_add':
        selected = _add_profile([x['profileName'] for x in profiles], avatars=[x for x in avatars.keys() if x not in used_avatars])

        if not selected:
            return _select_profile()

        selected['_avatar'] = avatars.get(selected['attributes']['avatar']['id'])

    _set_profile(selected)

def _set_profile(profile):
    api.set_profile(profile)

    if settings.getBool('kid_lockdown', False) and profile['attributes']['kidsModeEnabled']:
        userdata.set('kid_lockdown', True)

    userdata.set('avatar', profile['_avatar'])
    userdata.set('profile', profile['profileName'])
    gui.notification(_.PROFILE_ACTIVATED, heading=profile['profileName'], icon=profile['_avatar'])

def _delete_profile(profiles):
    options = []
    for index, profile in enumerate(profiles):
        options.append(profile['profileName'])

    index = gui.select(_.SELECT_DELETE_PROFILE, options=options)
    if index < 0:
        return

    selected = profiles[index]
    if gui.yes_no(_.DELETE_PROFILE_INFO, heading=_(_.DELTE_PROFILE_HEADER, name=selected['profileName'])) and api.delete_profile(selected).ok:
        gui.notification(_.PROFILE_DELETED, heading=profile['profileName'], icon=profile['_avatar'])

def _add_profile(taken_names, avatars):
    name = ''
    while True:
        name = gui.input(_.PROFILE_NAME, default=name).strip()
        if not name:
            return

        elif name in taken_names:
            gui.notification(_(_.PROFILE_NAME_TAKEN, name=name))
            
        else:
            break

    kids = gui.yes_no(_.KIDS_PROFILE_INFO, heading=_.KIDS_PROFILE)

    profile = api.add_profile(name, kids=kids, avatar=random.choice(avatars) if avatars else None)
    if 'errors' in profile:
        gui.ok(profile['errors'][0].get('description'))

    return profile

@plugin.route()
def collection(slug, content_class, label=None, **kwargs):
    data = api.collection_by_slug(slug, content_class)
    
    folder = plugin.Folder(label or _get_text(data['texts'], 'title', 'collection'), fanart=_image(data.get('images', []), 'fanart'))
    thumb  = _image(data.get('images', []), 'thumb')

    for row in data['containers']:
        _type = row.get('type')
        _set  = row.get('set')

        if _set.get('refIdType') == 'setId':
            set_id = _set['refId']
        else:
            set_id = _set.get('setId')

        if not set_id:
            return None

        if _set['contentClass'] in ('hero', 'brand', 'episode', 'WatchlistSet'):
            items = _process_rows(_set['items'], _set['contentClass'])
            folder.add_items(items)
            continue

        elif _set['contentClass'] == 'BecauseYouSet':
            data = api.set_by_setid(set_id, _set['contentClass'], page_size=0)
            title = _get_text(data['texts'], 'title', 'set')

        else:
            title = _get_text(_set['texts'], 'title', 'set')

        folder.add_item(
            label = title,
            art   = {'thumb': thumb},
            path  = plugin.url_for(sets, set_id=set_id, set_type=_set['contentClass']),
        )

    return folder

@plugin.route()
def sets(set_id, set_type, page=1, **kwargs):
    page = int(page)
    data = api.set_by_setid(set_id, set_type, page=page, page_size=PAGE_SIZE)

    folder = plugin.Folder(_get_text(data['texts'], 'title', 'set'), sort_methods=[xbmcplugin.SORT_METHOD_UNSORTED, xbmcplugin.SORT_METHOD_VIDEO_YEAR, xbmcplugin.SORT_METHOD_LABEL])

    items = _process_rows(data['items'], data['contentClass'])
    folder.add_items(items)

    if (data['meta']['page_size'] + data['meta']['offset']) < data['meta']['hits']:
        folder.add_item(
            label = _(_.NEXT_PAGE, page=page+1),
            path  = plugin.url_for(sets, set_id=set_id, set_type=set_type, page=page+1),
        )

    return folder

def _process_rows(rows, content_class=None):
    items = []

    for row in rows:
        item = None
        content_type = row.get('type')

        if content_type == 'DmcVideo':
            program_type = row.get('programType')

            if program_type == 'episode':
                if content_class in ('episode', 'ContinueWatchingSet'):
                    item = _parse_video(row)
                else:
                    item = _parse_series(row)
            else:
                item = _parse_video(row)

        elif content_type == 'DmcSeries':
            item = _parse_series(row)

        elif content_type == 'StandardCollection':
            item = _parse_collection(row)

        if not item:
            continue

        if content_class == 'WatchlistSet':
            item.context.insert(0, (_.DELETE_WATCHLIST, 'XBMC.RunPlugin({})'.format(plugin.url_for(delete_watchlist, content_id=row['contentId']))))
        elif content_type == 'DmcSeries' or (content_type == 'DmcVideo' and program_type != 'episode'):
            item.context.insert(0, (_.ADD_WATCHLIST, 'XBMC.RunPlugin({})'.format(plugin.url_for(add_watchlist, content_id=row['contentId'], title=item.label))))

        items.append(item)

    return items

@plugin.route()
def add_watchlist(content_id, title=None, **kwargs):
    gui.notification(_.ADDED_WATCHLIST, heading=title)
    api.add_watchlist(content_id)

@plugin.route()
def delete_watchlist(content_id, **kwargs):
    api.delete_watchlist(content_id)
    gui.refresh()

def _parse_collection(row):
    return plugin.Item(
        label = _get_text(row['texts'], 'title', 'collection'),
        info  = {'plot': _get_text(row['texts'], 'description', 'collection')},
        art   = {'thumb': _image(row['images'], 'thumb'), 'fanart': _image(row['images'], 'fanart')},
        path  = plugin.url_for(collection, slug=row['collectionGroup']['slugs'][0]['value'], content_class=row['collectionGroup']['contentClass']),
    )
            
def _parse_series(row):
    return plugin.Item(
        label = _get_text(row['texts'], 'title', 'series'),
        art = {'thumb': _image(row['images'], 'thumb'), 'fanart': _image(row['images'], 'fanart')},
        info = {
            'plot': _get_text(row['texts'], 'description', 'series'),
            'year': row['releases'][0]['releaseYear'],
          #  'mediatype': 'tvshow',
            'genre': row['genres'],
        },
        path = plugin.url_for(series, series_id=row['encodedSeriesId']),
    )

def _parse_season(row, series):
    title = _(_.SEASON, season=row['seasonSequenceNumber'])
    
    return plugin.Item(
        label = title,
        info  = {
            'plot': _get_text(row['texts'], 'description', 'season'), 
           # 'mediatype' : 'season'
        },
        art   = {'thumb': _image(row['images'] or series['images'], 'thumb')},
        path  = plugin.url_for(season, season_id=row['seasonId'], title=title),
    )

def _parse_video(row):
    item = plugin.Item(
        label = _get_text(row['texts'], 'title', 'program'),
        info  = {
            'plot': _get_text(row['texts'], 'description', 'program'),
            'duration': row['mediaMetadata']['runtimeMillis']/1000, 
            'year': row['releases'][0]['releaseYear'],
            'dateadded': row['releases'][0]['releaseDate'] or row['releases'][0]['releaseYear'],
            'mediatype': 'movie',
            'genre': row['genres'],
            'season': row['seasonSequenceNumber'],
            'episode': row['episodeSequenceNumber'],
        },
        art  = {'thumb': _image(row['images'], 'thumb'), 'fanart': _image(row['images'], 'fanart')},
        path = plugin.url_for(play, content_id=row['contentId']),
        playable = True,
    )

    if _get_milestone(row.get('milestones'), 'intro_end'):
        if settings.getBool('skip_intros', False):
            item.context.append((_.INCLUDE_INTRO, 'XBMC.PlayMedia({},noresume)'.format(plugin.url_for(play, content_id=row['contentId'], skip_intro=0))))
        else:
            item.context.append((_.SKIP_INTRO, 'XBMC.PlayMedia({},noresume)'.format(plugin.url_for(play, content_id=row['contentId'], skip_intro=1))))

    item.context.append((_.CONTINUE_WATCHING, 'XBMC.PlayMedia({},noresume)'.format(plugin.url_for(play, content_id=row['contentId'], continue_watching=1))))

    if row['programType'] == 'episode':
        item.info.update({
            'mediatype' : 'episode',
            'tvshowtitle': _get_text(row['texts'], 'title', 'series'),
        })
    else:
        item.context.append((_.EXTRAS, "Container.Update({})".format(plugin.url_for(extras, family_id=row['encodedParentOf']))))
        item.context.append((_.SUGGESTED, "Container.Update({})".format(plugin.url_for(suggested, family_id=row['encodedParentOf']))))

    return item

def _image(data, _type='thumb'):
    _types = {
        'thumb': (('thumbnail','1.78'), ('tile','1.78')),
        'fanart': (('background','1.78'), ('background_details','1.78'), ('hero_collection','1.78')),
    }

    selected = _types[_type]

    images = []
    for row in data:
        for index, _type in enumerate(selected):
            if not row['url']:
                continue

            if row['purpose'] == _type[0] and str(row['aspectRatio']) == _type[1]:
                images.append([index, row])

    if not images:
        return None

    chosen = sorted(images, key=lambda x: (x[0], -x[1]['masterWidth']))[0][1]

    if _type == 'fanart':
        return chosen['url'] + '/scale?aspectRatio=1.78&format=jpeg'
    else:
        return chosen['url'] + '/scale?width=800&aspectRatio=1.78&format=jpeg'

def _get_text(texts, field, source):
    _types = ['medium', 'brief', 'full']

    candidates = []
    for row in texts:
        if row['field'] == field and source == row['sourceEntity']:
            if not row['content']:
                continue

            if row['type'] not in _types:
                _types.append(row['type'])

            candidates.append((_types.index(row['type']), row['content']))

    if not candidates:
        return None

    return sorted(candidates, key=lambda x: x[0])[0][1]

@plugin.route()
def series(series_id, **kwargs):
    data = api.series_bundle(series_id, page_size=0)

    title = _get_text(data['series']['texts'], 'title', 'series')
    folder = plugin.Folder(title, fanart=_image(data['series']['images'], 'fanart'))

    for row in data['seasons']['seasons']:
        item = _parse_season(row, data['series'])
        folder.add_items(item)

    if data['extras']['videos']:
        folder.add_item(
            label = (_.EXTRAS),
            art   = {'thumb': _image(data['series']['images'], 'thumb')},
            path  = plugin.url_for(extras, series_id=series_id),
        )

    if data['related']['items']:
        folder.add_item(
            label = _.SUGGESTED,
            art   = {'thumb': _image(data['series']['images'], 'thumb')},
            path  = plugin.url_for(suggested, series_id=series_id),
        )

    return folder

@plugin.route()
def season(season_id, title, **kwargs):
    data = api.episodes([season_id,], page_size=PAGE_SIZE)
    
    folder = plugin.Folder(title, sort_methods=[xbmcplugin.SORT_METHOD_EPISODE, xbmcplugin.SORT_METHOD_UNSORTED, xbmcplugin.SORT_METHOD_LABEL, xbmcplugin.SORT_METHOD_DATEADDED])

    items = _process_rows(data['videos'], content_class='ContinueWatchingSet')
    folder.add_items(items)

    return folder

@plugin.route()
def suggested(family_id=None, series_id=None, **kwargs):
    if family_id:
        data = api.video_bundle(family_id)
    elif series_id:
        data = api.series_bundle(series_id, page_size=0)

    folder = plugin.Folder(_.SUGGESTED)

    items = _process_rows(data['related']['items'])
    folder.add_items(items)

    return folder

@plugin.route()
def extras(family_id=None, series_id=None, **kwargs):
    if family_id:
        data = api.video_bundle(family_id)
        fanart = _image(data['video']['images'], 'fanart')
    elif series_id:
        data = api.series_bundle(series_id, page_size=0)
        fanart = _image(data['series']['images'], 'fanart')

    folder = plugin.Folder(_.EXTRAS, fanart=fanart)

    items = _process_rows(data['extras']['videos'])
    folder.add_items(items)

    return folder

@plugin.route()
def search(query=None, page=1, **kwargs):
    page  = int(page)

    if not query:
        query = gui.input(_.SEARCH, default=userdata.get('search', '')).strip()
        if not query:
            return

        userdata.set('search', query)

    folder = plugin.Folder(_(_.SEARCH_FOR, query=query))

    data = api.search(query, page=page, page_size=PAGE_SIZE)

    hits = [x['hit'] for x in data['hits']]
    items = _process_rows(hits)
    folder.add_items(items)

    if not folder.items:
        return gui.ok(_.NO_RESULTS, heading=folder.title)

    elif (data['meta']['page_size'] + data['meta']['offset']) < data['meta']['hits']:
        folder.add_item(
            label = _(_.NEXT_PAGE, page=page+1),
            path  = plugin.url_for(search, query=query, page=page+1),
        )

    return folder

@plugin.route()
@plugin.login_required()
def play(content_id, skip_intro=None, continue_watching=0, **kwargs):
    if KODI_VERSION > 18:
        ver_required = '2.5.5'
    else:
        ver_required = '2.4.4'

    ia = inputstream.Widevine(
        license_key = api.get_config()['services']['drm']['client']['endpoints']['widevineLicense']['href'],
        manifest_type = 'hls',
        mimetype = 'application/vnd.apple.mpegurl',
    )

    if not ia.check() or not inputstream.require_version(ver_required):
        plugin.exception(_(_.IA_VER_ERROR, kodi_ver=KODI_VERSION, ver_required=ver_required))

    video = api.videos(content_id)['videos'][0]
    playback_url = video['mediaMetadata']['playbackUrls'][0]['href']
    media_stream = api.media_stream(playback_url)
    
    headers = api.session.headers
    headers['_proxy_default_language'] = video['originalLanguage']

    item = plugin.Item(
        path = media_stream,
        inputstream = ia,
        headers = headers,
        properties = {
            'inputstream.adaptive.original_audio_language': video['originalLanguage'],
        },
        use_proxy = True,
    )

    resume_from = None
    if int(continue_watching):
        if video['programType'] == 'episode':
            data = api.continue_watching_series(video['encodedSeriesId'])
            for row in data['episodesWithProgress']:
                if row['contentId'] == video['contentId']:
                    resume_from = row['userMeta']['playhead']
        else:
            data = api.continue_watching(video['family']['encodedFamilyId'])
            if data.get('resume'):
                resume_from = data['resume']['userMeta']['playhead']

    if not resume_from and (int(skip_intro) if skip_intro is not None else settings.getBool('skip_intros', False)):
        resume_from = _get_milestone(video.get('milestones'), 'intro_end', default=0) / 1000

    if resume_from:
        item.properties['ResumeTime'] = resume_from
        item.properties['TotalTime']  = resume_from

    if settings.getBool('wv_secure', False):
        item.properties['inputstream.adaptive.license_flags'] = 'force_secure_decoder'

    return item

@plugin.route()
def logout(**kwargs):
    if not gui.yes_no(_.LOGOUT_YES_NO):
        return

    api.logout()
    userdata.delete('kid_lockdown')
    userdata.delete('avatar')
    userdata.delete('profile')
    gui.refresh()

def _get_milestone(milestones, key, default=None):
    if not milestones:
        return default

    for milestone in milestones:
        if milestone['milestoneType'] == key:
            return milestone['milestoneTime'][0]['startMillis']

    return default