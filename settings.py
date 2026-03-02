BOT_NAME = "webnovelscraper"

SPIDER_MODULES = ["spiders"]
NEWSPIDER_MODULE = "spiders"

DOWNLOADER_MIDDLEWARES = {
    "auth.middleware.AuthMiddleware": 300,
}

COOKIES_ENABLED = True
RETRY_ENABLED = True
RETRY_TIMES = 5
LOG_LEVEL = "INFO"
