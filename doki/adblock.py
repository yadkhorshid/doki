"""Blocks common ad, popup and tracker hosts in the capture browser."""

import re

AD_HOSTS = (
    # Ad networks and popunders common on streaming sites.
    "doubleclick.net", "googlesyndication.com", "googleadservices.com", "adservice.google.com",
    "adnxs.com", "popads.net", "popcash.net", "propellerads.com", "propellerclick.com",
    "onclickads.net", "onclkds.com", "clickadu.com", "adsterra.com", "adsterratech.com",
    "exoclick.com", "exdynsrv.com", "juicyads.com", "trafficjunky.net", "hilltopads.net",
    "a-ads.com", "monetag.com", "realsrv.com", "acint.net", "adcash.com", "adskeeper.com",
    "mgid.com", "taboola.com", "outbrain.com", "revcontent.com", "galaksion.com",
    "bidgear.com", "pubmatic.com", "rubiconproject.com", "criteo.com", "amazon-adsystem.com",
    # Analytics and trackers.
    "google-analytics.com", "googletagmanager.com", "mc.yandex.ru", "histats.com",
    "scorecardresearch.com", "quantserve.com", "hotjar.com", "clarity.ms",
)
AD_URL_PATTERN = re.compile(
    r"^https?://([^/?#]*\.)?(" + "|".join(re.escape(host) for host in AD_HOSTS) + r")(:\d+)?([/?#]|$)",
    re.IGNORECASE,
)


def block_ads(context):
    """Aborts requests to known ad hosts and closes popup tabs and windows."""
    context.route(AD_URL_PATTERN, lambda route: route.abort())
    context.on("page", lambda page: page.close() if page.opener() else None)
