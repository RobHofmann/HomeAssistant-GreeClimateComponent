import sys
import time
import json
import datetime
import hashlib
import requests
import logging

_LOGGER = logging.getLogger(__name__)
GREE_KEY = "d15cb842b7fd704ebcf8276f34cbd771"
SEP = "_"

class GreeCloud:
    def __init__(self, user=None, password=None):
        self._user = user
        self._password = password
        self._request = requests.session()
        self._cookies = {}
        self._headers = {'Host': 'account.xiaomi.com',
                         'Connection': 'keep-alive',
                         'Upgrade-Insecure-Requests': '1',
                         'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/65.0.3325.181 Safari/537.36',
                         'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                         'Accept-Encoding': 'gzip, deflate, br',
                         'Accept-Language': 'zh-CN,zh;q=0.9'}
        if not self._login():
            _LOGGER.error("登录失败")
            return

    def _login(self):
        url = 'https://grih.gree.com/App/UserLoginV2'
        request = UserLoginRequest.gen(self._user, self._password)
        response = self._post(url, request)
        if response['r'] != 200:
            return False
        self._uid = response['uid']
        self._token = response['token']
        return True

    def _post(self, url, data):
        _LOGGER.info(data.to_json())
        r = self._request.post(url, headers=self._headers, data=data.to_json(), timeout=30, cookies=self._cookies, verify=False)
        _LOGGER.info(r.text)
        return json.loads(r.text)

    def get_home_dev(self):
        url = 'https://grih.gree.com/App/GetDevsOfUserHomes'
        request = HomeDevRequest.gen(self._uid, self._token)
        response = self._post(url, request)
        if response['r'] != 200:
            return False
        return response['homes'][0]['devs']

class JsonObject:
    def to_dict(self):
        _dict = {}
        _dict.update(self.__dict__)
        for i in _dict:
            _v = _dict[i]
            if isinstance(_v, JsonObject):
                _dict[i] = _v.to_dict()
        return _dict

    def to_json(self):
        return json.dumps(self.to_dict())

class Api(JsonObject):
    def __init__(self):
        self.appId = "5686063144437916735"
        self.r = 0
        self.t = ""
        self.vc = ""

    @staticmethod
    def gen():
        api = Api()
        now = datetime.datetime.utcnow()
        api.t = now.strftime("%Y-%m-%d %H:%M:%S")
        api.r = (int(round(time.time() * 1000)))
        api.vc = md5(api.appId + SEP + GREE_KEY + SEP + api.t + SEP + str(api.r))
        return api

class UserLoginRequest(JsonObject):
    @staticmethod
    def gen(user, pwd):
        request = UserLoginRequest()
        request.app = "æ ¼å\u008A\u009B+"
        request.appver = "201901178"
        request.devId = "ffffffff-f534-9766-ffff-ffffc2e834d9"
        request.devModel = "MuMu"
        request.api = Api.gen()
        request.user = user
        request.t = request.api.t
        request.psw = md5(md5(md5(pwd) + pwd) + request.t)
        request.datVc = get_dat_vc(request.user, request.psw, request.t)
        return request

class HomeDevRequest(JsonObject):
    @staticmethod
    def gen(uid, token):
        request = HomeDevRequest()
        request.api = Api.gen()
        request.uid = uid
        request.token = token
        request.datVc = get_dat_vc(request.token, request.uid)
        return request

def get_dat_vc(*datas):
    result = GREE_KEY
    for data in datas:
        result = result + SEP + str(data)
    return md5(result)

def md5(raw):
    m = hashlib.md5()
    m.update(raw.encode("utf8"))
    return m.hexdigest()

user = sys.argv[1]
password = sys.argv[2]
client = GreeCloud(user, password)
devs = client.get_home_dev()
for dev in devs:
    if not dev['pmac']: continue
    print(dev['name'], dev['mac'])