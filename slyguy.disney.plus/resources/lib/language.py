from slyguy.language import BaseLanguage

class Language(BaseLanguage):
    ASK_USERNAME         = 30001
    ASK_PASSWORD         = 30002
    LOGIN_ERROR          = 30003
    MOVIES               = 30004
    SERIES               = 30005
    ORIGINALS            = 30006
    SEARCH               = 30007
    NEXT_PAGE            = 30008
    WV_SECURE            = 30009
    SUGGESTED            = 30010
    FEATURED             = 30011
    SEASON               = 30012
    EXTRAS               = 30013
    
_ = Language()