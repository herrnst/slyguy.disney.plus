import json
import uuid
from time import time

from slyguy import userdata, settings
from slyguy.session import Session
from slyguy.exceptions import Error
from slyguy import mem_cache

from kodi_six import xbmc

from .constants import HEADERS, AUTH_URL, API_KEY, CONTENT_URL, PLAY_URL
from .language import _

class APIError(Error):
    pass

class API(object):
    def new_session(self):
        self.logged_in = False
        self._session  = Session(HEADERS)
        self._set_authentication(userdata.get('access_token'))

    @mem_cache.cached(60*60, key='transaction_id')
    def _transaction_id(self):
        return str(uuid.uuid4())

    @property
    def session(self):
        return self._session
        
    def _set_authentication(self, access_token):
        if not access_token:
            return

        self._session.headers.update({'authorization': 'Bearer {}'.format(access_token)})
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

    def _oauth_token(self, payload, anonymous=False):
        headers = {
            'authorization': 'Bearer {}'.format(API_KEY),
        }

        token_data = self._session.post(AUTH_URL + '/token', data=payload, headers=headers).json()

        if 'errors' in token_data:
            raise APIError(_(_.LOGIN_ERROR, msg=token_data['errors'][0].get('description')))
        elif 'error' in token_data:
            raise APIError(_(_.LOGIN_ERROR, msg=token_data.get('error_description')))

        self._set_authentication(token_data['access_token'])

        if anonymous:
            return

        userdata.set('access_token', token_data['access_token'])
        userdata.set('expires', int(time() + token_data['expires_in'] - 15))

        if 'refresh_token' in token_data:
            userdata.set('refresh_token', token_data['refresh_token'])

    def login(self, username, password):
        self.logout()

        headers = {
            'authorization': 'Bearer {}'.format(API_KEY),
        }

        payload = {
            'deviceFamily': 'browser',
            'applicationRuntime': 'chrome',
            'deviceProfile': 'windows',
            'attributes': {},
        }

        device_data = self._session.post(AUTH_URL + '/devices', json=payload, headers=headers).json()

        payload = {
            'subject_token': device_data['assertion'],
            'subject_token_type': 'urn:bamtech:params:oauth:token-type:device',
            'platform': 'browser',
            'grant_type': 'urn:ietf:params:oauth:grant-type:token-exchange',
        }

        self._oauth_token(payload, anonymous=True)

        payload = {
            'email':    username,
            'password': password,
        }

        login_data = self._session.post(AUTH_URL + '/idp/login', json=payload).json()

        if 'errors' in login_data:
            raise APIError(_(_.LOGIN_ERROR, msg=login_data['errors'][0].get('description')))
        elif 'error' in login_data:
            raise APIError(_(_.LOGIN_ERROR, msg=login_data.get('error_description')))

        grant_data = self._session.post(AUTH_URL + '/accounts/grant', json={'id_token': login_data['id_token']}).json()

        payload = {
            'subject_token': grant_data['assertion'],
            'subject_token_type': 'urn:bamtech:params:oauth:token-type:account',
            'platform': 'browser',
            'grant_type': 'urn:ietf:params:oauth:grant-type:token-exchange',
        }

        self._oauth_token(payload)

    def search(self, query, page=1, page_size=20):
        variables = {
            'preferredLanguage': ['en-GB'],
            'index': 'disney_global',
            'q': query,
            'page': page,
            'pageSize': page_size,
            'contentTransactionId': self._transaction_id(),
        }

        return self._session.get(CONTENT_URL + '/core/disneysearch', params={'variables': json.dumps(variables)}).json()['data']['disneysearch']

    def video_bundle(self, family_id):
        variables = {
            'preferredLanguage': ['en-GB'],
            'familyId': family_id,
            'contentTransactionId': self._transaction_id(),
        }

        return self._session.get(CONTENT_URL + '/core/DmcVideoBundle', params={'variables': json.dumps(variables)}).json()['data']['DmcVideoBundle']

    def series_bundle(self, series_id, page=1, page_size=12):
        variables = {
            'preferredLanguage': ['en-GB'],
            'seriesId': series_id,
            'episodePage': page,
            'episodePageSize': page_size,
            'contentTransactionId': self._transaction_id(),
        }

        return self._session.get(CONTENT_URL + '/core/DmcSeriesBundle', params={'variables': json.dumps(variables)}).json()['data']['DmcSeriesBundle']

    def episodes(self, season_ids, page=1, page_size=12):
        variables = {
            'preferredLanguage': ['en-GB'],
            'seasonId': season_ids,
            'episodePage': page,
            'episodePageSize': page_size,
            'contentTransactionId': self._transaction_id(),
        }

        return self._session.get(CONTENT_URL + '/core/DmcEpisodes', params={'variables': json.dumps(variables)}).json()['data']['DmcEpisodes']

    def collection_by_slug(self, slug, content_class):
        variables = {
            'preferredLanguage': ['en-GB'],
            'contentClass': content_class,
            'slug': slug,
            'contentTransactionId': self._transaction_id(),
        }

        return self._session.get(CONTENT_URL + '/disney/CollectionBySlug', params={'variables': json.dumps(variables)}).json()['data']['CollectionBySlug']

    def set_by_setid(self, set_id, set_type, page=1, page_size=20):
        variables = {
            'preferredLanguage': ['en-GB'],
            'setId': set_id,
            'setType': set_type,
            'page': page,
            'pageSize': page_size,
            'contentTransactionId': self._transaction_id(),
        }

        return self._session.get(CONTENT_URL + '/disney/SetBySetId', params={'variables': json.dumps(variables)}).json()['data']['SetBySetId']

    def media_stream(self, media_id):
        self._refresh_token()

        scenario = 'restricted-drm-ctr-sw'
      #  scenario = 'android~unlimited' if (xbmc.getCondVisibility('system.platform.android') and settings.getBool('wv_secure', False)) else 'restricted-drm-ctr-sw'
        href = PLAY_URL.format(media_id=media_id, scenario=scenario)
        headers = {'accept': 'application/vnd.media-service+json; version=2', 'authorization': userdata.get('access_token')}

        return self._session.get(href, headers=headers).json()['stream']['complete']

    def logout(self):
        userdata.delete('access_token')
        userdata.delete('expires')
        userdata.delete('refresh_token')
        mem_cache.delete('transaction_id')
        
        self.new_session()

    # @cached(60*60)
    # def videos(self, content_id):
    #     variables = {
    #         'preferredLanguage': ['en-GB'],
    #         'contentId': content_id,
    #         'contentTransactionId': self._transaction_id(),
    #     }

    #     return self._session.get(CONTENT_URL + '/core/DmcVideos', params={'variables': json.dumps(variables)}).json()['data']['DmcVideos']