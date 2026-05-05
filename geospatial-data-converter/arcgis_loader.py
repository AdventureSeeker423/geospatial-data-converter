from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import geopandas as gpd


async def get_arcgis_data(
    url: str,
    *,
    session_factory: Callable[[], Any] | None = None,
    feature_layer_cls: Any = None,
) -> tuple[str, gpd.GeoDataFrame]:
    if session_factory is None:
        from aiohttp import ClientSession

        session_factory = ClientSession

    if feature_layer_cls is None:
        from restgdf import FeatureLayer

        feature_layer_cls = FeatureLayer

    async with session_factory() as session:
        layer = await feature_layer_cls.from_url(url, session=session)
        gdf = await layer.get_gdf()
    return layer.name, gdf
