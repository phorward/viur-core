import logging
import warnings

from .adapter import DatabaseAdapter, ViurTagsSearchAdapter
from .instance import SkeletonInstance
from .meta import MetaSkel, MetaBaseSkel, BaseSkeleton
from .relskel import RelSkel, RefSkel
from .skeleton import Skeleton, SeoKeyBone
from .utils import SkelList, skeletonByKind, listKnownSkeletons, iterAllSkelClasses

from .. import db

# Forward our references to SkelInstance to the database (needed for queries)
db.config["SkeletonInstanceRef"] = SkeletonInstance

# DEPRECATED ATTRIBUTES HANDLING

__DEPRECATED_NAMES = {
    # stuff prior viur-core < 3.6
    "seoKeyBone": ("SeoKeyBone", SeoKeyBone),
}


def __getattr__(attr: str) -> object:
    if entry := __DEPRECATED_NAMES.get(attr):
        func = entry[1]
        msg = f"{attr} was replaced by {entry[0]}"
        warnings.warn(msg, DeprecationWarning, stacklevel=2)
        logging.warning(msg, stacklevel=2)
        return func

    return super(__import__(__name__).__class__).__getattribute__(attr)


__all__ = [
    BaseSkeleton,
    DatabaseAdapter,
    iterAllSkelClasses,
    listKnownSkeletons,
    MetaBaseSkel,
    MetaSkel,
    RefSkel,
    RelSkel,
    SeoKeyBone,
    Skeleton,
    skeletonByKind,
    SkeletonInstance,
    SkelList,
    ViurTagsSearchAdapter,
]
