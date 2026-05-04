import asyncio

from arcgis_loader import get_arcgis_data


class FakeSession:
    def __init__(self, tracker: dict[str, object]) -> None:
        self.tracker = tracker

    async def __aenter__(self) -> "FakeSession":
        self.tracker["entered"] = True
        self.tracker["session"] = self
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.tracker["exited"] = True


class FakeLayer:
    def __init__(self, tracker: dict[str, object], gdf: object) -> None:
        self.tracker = tracker
        self.name = "public-layer"
        self._gdf = gdf

    async def get_gdf(self) -> object:
        self.tracker["get_gdf_called"] = True
        return self._gdf


class FakeFeatureLayer:
    tracker: dict[str, object] = {}
    gdf: object = object()

    @classmethod
    async def from_url(cls, url: str, *, session: object) -> FakeLayer:
        cls.tracker["url"] = url
        cls.tracker["session_arg"] = session
        return FakeLayer(cls.tracker, cls.gdf)


def test_get_arcgis_data_uses_get_gdf() -> None:
    tracker: dict[str, object] = {}
    expected_gdf = object()
    FakeFeatureLayer.tracker = tracker
    FakeFeatureLayer.gdf = expected_gdf

    def session_factory() -> FakeSession:
        return FakeSession(tracker)

    name, gdf = asyncio.run(
        get_arcgis_data(
            "https://example.test/FeatureServer/0",
            session_factory=session_factory,
            feature_layer_cls=FakeFeatureLayer,
        ),
    )

    assert tracker["url"] == "https://example.test/FeatureServer/0"
    assert tracker["get_gdf_called"] is True
    assert name == "public-layer"
    assert gdf is expected_gdf


def test_get_arcgis_data_closes_created_session() -> None:
    tracker: dict[str, object] = {}
    FakeFeatureLayer.tracker = tracker
    FakeFeatureLayer.gdf = object()

    def session_factory() -> FakeSession:
        return FakeSession(tracker)

    asyncio.run(
        get_arcgis_data(
            "https://example.test/FeatureServer/0",
            session_factory=session_factory,
            feature_layer_cls=FakeFeatureLayer,
        ),
    )

    assert tracker["entered"] is True
    assert tracker["exited"] is True
    assert tracker["session_arg"] is tracker["session"]
