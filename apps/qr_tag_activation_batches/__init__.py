"""qr-tag-activation-batches — pre-allocated batches of physical QR tags.

Extracted from FindItNow (FIN/apps/activation). See README.md for the
distribution flow and integration steps.

Flow recap:

    Admin generates an ActivationBatch (size N) →
    server bulk-creates N ActivationCode rows, each with a unique
    pre-allocated ``qr_slug`` and (optionally) a 6-digit ``activation_code``
    → tags are printed with the qr_slug encoded in the QR → customer scans
    → enters the code (or uploads a proof photo for PHOTO-mode batches) →
    the code is marked consumed and a domain object is linked.

The slug is printed on the tag; the code is delivered separately
(scratch-off carton, CSV file, or never at all for PHOTO-mode tags).
"""

default_app_config = "qr_tag_activation_batches.apps.QrTagActivationBatchesConfig"
