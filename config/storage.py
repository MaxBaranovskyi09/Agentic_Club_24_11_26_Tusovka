from whitenoise.storage import CompressedManifestStaticFilesStorage


class ForgivingManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """Хешовані імена після collectstatic; якщо collectstatic ще не запускали — звичайні імена,
    а не 500 на кожній сторінці (WhiteNoise з USE_FINDERS віддасть файли напряму)."""

    manifest_strict = False

    def hashed_name(self, name, content=None, filename=None):
        try:
            return super().hashed_name(name, content, filename)
        except ValueError:
            return name
