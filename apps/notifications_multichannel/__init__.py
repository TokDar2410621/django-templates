"""notifications-multichannel — Email (Resend) + Web Push + SMS (Twilio).

Extracted from FindItNow (FIN/apps/notifications). A unified facade for the
three transactional channels every consumer app needs, with degraded-mode
fallbacks so missing credentials don't crash the boot.

See README.md for integration, SETTINGS.md for configuration.
"""
default_app_config = "notifications_multichannel.apps.NotificationsMultichannelConfig"
