from . import apns, expo, fcm, webpush

BACKENDS = {
    "web": webpush,
    "fcm": fcm,
    "apns": apns,
    "expo": expo,
}
