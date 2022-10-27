import json
import uuid
from time import time

from slyguy import userdata, settings, mem_cache
from slyguy.session import Session
from slyguy.exceptions import Error
from slyguy.util import get_kodi_setting
from slyguy.log import log

from kodi_six import xbmc

from .constants import HEADERS, CONFIG_URL, API_KEY, LANGUAGE_OPTIONS, PROFILE_LANGUAGE, KODI_LANGUAGE
from .language import _

class APIError(Error):
    pass

class API(object):
    def new_session(self):
        self.logged_in = False
        self._session  = Session(HEADERS)
        self._set_authentication(userdata.get('access_token'))
        self._set_language()

    @mem_cache.cached(60*60)
    def get_config(self):
        return self._session.get(CONFIG_URL).json()

    def _set_language(self):
        self._language = settings.getEnum('app_language', LANGUAGE_OPTIONS, default=KODI_LANGUAGE)

        if self._language == PROFILE_LANGUAGE:
            self._language = userdata.get('profile_language')

        if not self._language or self._language == KODI_LANGUAGE:
            value = get_kodi_setting('locale.language', default='en')
            value = value.split('.')[-1]
            
            split = value.split('_')
            if len(split) > 1:
                split[1] = split[1].upper()

            self._language = '-'.join(split)

        log.debug("App Language Set to: {}".format(self._language))

    @mem_cache.cached(60*60, key='transaction_id')
    def _transaction_id(self):
        return str(uuid.uuid4())

    @property
    def session(self):
        return self._session
        
    def _set_authentication(self, access_token):
        if not access_token:
            return

        self._session.headers.update({'Authorization': 'Bearer {}'.format(access_token)})
        self._session.headers.update({'x-bamsdk-transaction-id': self._transaction_id()})
        self.logged_in = True

    def _refresh_token(self):
        if userdata.get('expires', 0) > time():
            return

        payload = {
            'refresh_token': userdata.get('refresh_token'),
            'grant_type': 'refresh_token',
            'platform': 'browser',
        }

        self._oauth_token(payload)

    def _oauth_token(self, payload):
        headers = {
            'Authorization': 'Bearer {}'.format(API_KEY),
        }

        endpoint = self.get_config()['services']['token']['client']['endpoints']['exchange']['href']
        token_data = self._session.post(endpoint, data=payload, headers=headers).json()

        if 'errors' in token_data:
            raise APIError(_(_.LOGIN_ERROR, msg=token_data['errors'][0].get('description')))
        elif 'error' in token_data:
            raise APIError(_(_.LOGIN_ERROR, msg=token_data.get('error_description')))

        self._set_authentication(token_data['access_token'])

        userdata.set('access_token', token_data['access_token'])
        userdata.set('expires', int(time() + token_data['expires_in'] - 15))

        if 'refresh_token' in token_data:
            userdata.set('refresh_token', token_data['refresh_token'])

    def login(self, username, password):
        self.logout()

        try:
            self._do_login(username, password)
        except:
            self.logout()
            raise

    def _do_login(self, username, password):
        headers = {
            'Authorization': 'Bearer {}'.format(API_KEY),
        }

        payload = {
            'deviceFamily': 'android',
            'applicationRuntime': 'android',
            'deviceProfile': 'phone',
            'attributes': {},
        }
    
        endpoint = self.get_config()['services']['device']['client']['endpoints']['createDeviceGrant']['href']
        device_data = self._session.post(endpoint, json=payload, headers=headers).json()

        payload = {
            'subject_token': device_data['assertion'],
            'subject_token_type': 'urn:bamtech:params:oauth:token-type:device',
            'platform': 'android',
            'grant_type': 'urn:ietf:params:oauth:grant-type:token-exchange',
        }

        self._oauth_token(payload)

        payload = {
            'email':    username,
            'password': password,
        }

        endpoint = self.get_config()['services']['bamIdentity']['client']['endpoints']['identityLogin']['href']
        login_data = self._session.post(endpoint, json=payload).json()

        if 'errors' in login_data:
            raise APIError(_(_.LOGIN_ERROR, msg=login_data['errors'][0].get('description')))
        elif 'error' in login_data:
            raise APIError(_(_.LOGIN_ERROR, msg=login_data.get('error_description')))

        endpoint = self.get_config()['services']['account']['client']['endpoints']['createAccountGrant']['href']
        grant_data = self._session.post(endpoint, json={'id_token': login_data['id_token']}).json()

        payload = {
            'subject_token': grant_data['assertion'],
            'subject_token_type': 'urn:bamtech:params:oauth:token-type:account',
            'platform': 'android',
            'grant_type': 'urn:ietf:params:oauth:grant-type:token-exchange',
        }

        self._oauth_token(payload)

    def profiles(self):
        self._refresh_token()

        endpoint = self.get_config()['services']['account']['client']['endpoints']['getUserProfiles']['href']
        return self._session.get(endpoint).json()

    def active_profile(self):
        self._refresh_token()

        endpoint = self.get_config()['services']['account']['client']['endpoints']['getActiveUserProfile']['href']
        return self._session.get(endpoint).json()

    def set_profile(self, profile):
        self._refresh_token()

        endpoint   = self.get_config()['services']['account']['client']['endpoints']['setActiveUserProfile']['href'].format(profileId=profile['profileId'])
        grant_data = self._session.put(endpoint).json()

        payload = {
            'subject_token': grant_data['assertion'],
            'subject_token_type': 'urn:bamtech:params:oauth:token-type:account',
            'platform': 'android',
            'grant_type': 'urn:ietf:params:oauth:grant-type:token-exchange',
        }

        self._oauth_token(payload)

        userdata.set('profile_language', profile['attributes']['languagePreferences']['appLanguage'])

    def search(self, query, page=1, page_size=20):
        variables = {
            'preferredLanguage': [self._language],
            'index': 'disney_global',
            'q': query,
            'page': page,
            'pageSize': page_size,
            'contentTransactionId': self._transaction_id(),
        }

        endpoint = self.get_config()['services']['content']['client']['endpoints']['searchPersisted']['href'].format(queryId='core/disneysearch')
        return self._session.get(endpoint, params={'variables': json.dumps(variables)}).json()['data']['disneysearch']

    def video_bundle(self, family_id):
        variables = {
            'preferredLanguage': [self._language],
            'familyId': family_id,
            'contentTransactionId': self._transaction_id(),
        }

        endpoint = self.get_config()['services']['content']['client']['endpoints']['dmcVideos']['href'].format(queryId='core/DmcVideoBundle')
        return self._session.get(endpoint, params={'variables': json.dumps(variables)}).json()['data']['DmcVideoBundle']

    def series_bundle(self, series_id, page=1, page_size=12):
        variables = {
            'preferredLanguage': [self._language],
            'seriesId': series_id,
            'episodePage': page,
            'episodePageSize': page_size,
            'contentTransactionId': self._transaction_id(),
        }

        endpoint = self.get_config()['services']['content']['client']['endpoints']['dmcVideos']['href'].format(queryId='core/DmcSeriesBundle')
        return self._session.get(endpoint, params={'variables': json.dumps(variables)}).json()['data']['DmcSeriesBundle']

    def episodes(self, season_ids, page=1, page_size=12):
        variables = {
            'preferredLanguage': [self._language],
            'seasonId': season_ids,
            'episodePage': page,
            'episodePageSize': page_size,
            'contentTransactionId': self._transaction_id(),
        }

        endpoint = self.get_config()['services']['content']['client']['endpoints']['dmcVideos']['href'].format(queryId='core/DmcEpisodes')
        return self._session.get(endpoint, params={'variables': json.dumps(variables)}).json()['data']['DmcEpisodes']

    def collection_by_slug(self, slug, content_class):
        variables = {
            'preferredLanguage': [self._language],
            'contentClass': content_class,
            'slug': slug,
            'contentTransactionId': self._transaction_id(),
        }

        endpoint = self.get_config()['services']['content']['client']['endpoints']['dmcVideos']['href'].format(queryId='disney/CollectionBySlug')
        return self._session.get(endpoint, params={'variables': json.dumps(variables)}).json()['data']['CollectionBySlug']

    def set_by_setid(self, set_id, set_type, page=1, page_size=20):
        variables = {
            'preferredLanguage': [self._language],
            'setId': set_id,
            'setType': set_type,
            'page': page,
            'pageSize': page_size,
            'contentTransactionId': self._transaction_id(),
        }

        endpoint = self.get_config()['services']['content']['client']['endpoints']['dmcVideos']['href'].format(queryId='disney/SetBySetId')
        return self._session.get(endpoint, params={'variables': json.dumps(variables)}).json()['data']['SetBySetId']

    def videos(self, content_id):
        variables = {
            'preferredLanguage': [self._language],
            'contentId': content_id,
            'contentTransactionId': self._transaction_id(),
        }

        endpoint = self.get_config()['services']['content']['client']['endpoints']['dmcVideos']['href'].format(queryId='core/DmcVideos')
        return self._session.get(endpoint, params={'variables': json.dumps(variables)}).json()['data']['DmcVideos']

    def media_stream(self, playback_url):
        self._refresh_token()

        scenario = self.get_config()['services']['media']['extras']['restrictedPlaybackScenario']

        if xbmc.getCondVisibility('system.platform.android') and settings.getBool('wv_secure', False) and self.get_config()['services']['media']['extras']['isUhdAllowed']:
            scenario = self.get_config()['services']['media']['extras']['playbackScenarioDefault']
            if settings.getBool('h265', False):
                scenario += '-h265'
                if settings.getBool('dolby_vision', False):
                    scenario += '-dovi'
                elif settings.getBool('hdr10', False):
                    scenario += '-hdr10'

        headers = {'accept': 'application/vnd.media-service+json; version=4', 'authorization': userdata.get('access_token')}

        endpoint = playback_url.format(scenario=scenario)
        data = self._session.get(endpoint, headers=headers).json()
        if 'errors' in data:
            raise APIError('Blackout')

        return data['stream']['complete']

    def logout(self):
        userdata.delete('access_token')
        userdata.delete('expires')
        userdata.delete('refresh_token')
        mem_cache.delete('transaction_id')
        
        self.new_session()

# <item>android-mobile-drm-ctr</item>
# <item>android-mobile-drm-ctr-h265-sdr</item>
# <item>android-mobile-drm-ctr-h265-dovi</item>
# <item>android-mobile-drm-ctr-h265-hdr10</item>
# <item>android-tablet-drm-ctr</item>
# <item>android-tablet-drm-ctr-h265-sdr</item>
# <item>android-tablet-drm-ctr-h265-dovi</item>
# <item>android-tablet-drm-ctr-h265-hdr10</item>
# <item>android-tablet-high-drm-ctr</item>
# <item>android-tablet-high-drm-ctr-h265-sdr</item>
# <item>android-tablet-high-drm-ctr-h265-dovi</item>
# <item>android-tablet-high-drm-ctr-h265-hdr10</item>
# <item>android-tablet-sw-drm-ctr</item>
# <item>android-tablet-sw-drm-ctr-h265-sdr</item>
# <item>android-tablet-lfr-drm-ctr</item>
# <item>android-tv-drm-ctr</item>
# <item>android-tv-drm-ctr-h265-sdr</item>
# <item>android-tv-drm-ctr-h265-hdr10</item>
# <item>android-tv-drm-ctr-h265-dovi</item>

#  public final String generateScenario$sdk_core_api_release(MediaDescriptor mediaDescriptor, MediaServiceConfiguration mediaServiceConfiguration, boolean z) {
#         String str;
#         String defaultPlaybackScenario = mediaServiceConfiguration.getDefaultPlaybackScenario();
#         String basePlaybackScenario = mediaDescriptor.getBasePlaybackScenario();
#         AudioQuality audioQuality = null;
#         if (basePlaybackScenario == null || !(!StringsJVM.m50800a(basePlaybackScenario))) {
#             MediaPreferences mediaPreferences = mediaDescriptor.getMediaPreferences();
#             MediaQuality preferredMediaQuality = mediaPreferences != null ? mediaPreferences.getPreferredMediaQuality() : null;
#             if (preferredMediaQuality == null || !preferredMediaQuality.equals(MediaQuality.restricted)) {
#                 if (preferredMediaQuality != null && preferredMediaQuality.equals(MediaQuality.limited)) {
#                     defaultPlaybackScenario = defaultPlaybackScenario + '-' + MediaQuality.limited;
#                 }
#                 WidevineSecurityRequirements widevine = mediaServiceConfiguration.getSecurityCheckRequirements().getWidevine();
#                 if (widevine != null && widevine.getEnabled() && mediaServiceConfiguration.isUhdAllowed()) {
#                     MediaCapabilitiesProvider mediaCapabilitiesProvider2 = this.mediaCapabilitiesProvider;
#                     List<HdrType> supportedHdrTypes = mediaCapabilitiesProvider2 != null ? mediaCapabilitiesProvider2.getSupportedHdrTypes() : null;
#                     MediaCapabilitiesProvider mediaCapabilitiesProvider3 = this.mediaCapabilitiesProvider;
#                     List<SupportedCodec> supportedCodecs = mediaCapabilitiesProvider3 != null ? mediaCapabilitiesProvider3.getSupportedCodecs() : null;
#                     MediaCapabilitiesProvider mediaCapabilitiesProvider4 = this.mediaCapabilitiesProvider;
#                     HdcpSecurityLevel hdcpSecurityLevel = mediaCapabilitiesProvider4 != null ? mediaCapabilitiesProvider4.getHdcpSecurityLevel() : null;
#                     MediaCapabilitiesProvider mediaCapabilitiesProvider5 = this.mediaCapabilitiesProvider;
#                     WidevineSecurityLevel widevineSecurityLevel = mediaCapabilitiesProvider5 != null ? mediaCapabilitiesProvider5.getWidevineSecurityLevel() : null;
#                     WidevineSecurityRequirements widevine2 = mediaServiceConfiguration.getSecurityCheckRequirements().getWidevine();
#                     WidevineSecurityLevel minimumSecurityLevel = widevine2 != null ? widevine2.getMinimumSecurityLevel() : null;
#                     WidevineSecurityLevel widevineSecurityLevel2 = WidevineSecurityLevel.level1;
#                     boolean z2 = false;
#                     boolean z3 = minimumSecurityLevel == widevineSecurityLevel2 && widevineSecurityLevel == widevineSecurityLevel2 && z;
#                     if (minimumSecurityLevel != WidevineSecurityLevel.level1) {
#                         z2 = true;
#                     }
#                     if (z3 || z2 || C11223i.m50908a((Object) mediaDescriptor.getDrmType(), (Object) DrmType.PLAYREADY)) {
#                         if (supportedCodecs == null || !supportedCodecs.contains(SupportedCodec.h265)) {
#                             str = defaultPlaybackScenario;
#                         } else {
#                             str = defaultPlaybackScenario + "-h265";
#                             if (hdcpSecurityLevel == HdcpSecurityLevel.enhanced || hdcpSecurityLevel == HdcpSecurityLevel.unknown) {
#                                 if (mediaDescriptor.getHdrType() != null) {
#                                     str = str + '-' + mediaDescriptor.getHdrType();
#                                 } else if (supportedHdrTypes != null && supportedHdrTypes.contains(HdrType.DOLBY_VISION)) {
#                                     str = str + "-dovi";
#                                 } else if (supportedHdrTypes != null && supportedHdrTypes.contains(HdrType.HDR10)) {
#                                     str = str + "-hdr10";
#                                 }
#                             }
#                         }
#                         MediaCapabilitiesProvider mediaCapabilitiesProvider6 = this.mediaCapabilitiesProvider;
#                         if (mediaCapabilitiesProvider6 != null && mediaCapabilitiesProvider6.supportsAtmos()) {
#                             MediaPreferences mediaPreferences2 = mediaDescriptor.getMediaPreferences();
#                             if (mediaPreferences2 != null) {
#                                 audioQuality = mediaPreferences2.getPreferredAudioQuality();
#                             }
#                             if (audioQuality == AudioQuality.atmos) {
#                                 str = str + "-atmos";
#                             }
#                         }
#                     } else if (!C11223i.m50908a((Object) mediaDescriptor.getDrmType(), (Object) DrmType.PLAYREADY)) {
#                         str = mediaServiceConfiguration.getRestrictedPlaybackScenario();
#                     }
#                 }
#                 str = defaultPlaybackScenario;
#             } else {
#                 str = mediaServiceConfiguration.getRestrictedPlaybackScenario();
#             }
#         } else {
#             str = mediaDescriptor.getBasePlaybackScenario();
#             if (str == null) {
#                 C11223i.m50904a();
#                 throw null;
#             }
#         }
#         if (C11223i.m50908a((Object) mediaDescriptor.getAdInsertionStrategy(), (Object) AdInsertionStrategy.NONE)) {
#             return str;
#         }
#         return str + '~' + mediaDescriptor.getAdInsertionStrategy();