import enum
import typing as t
from collections import OrderedDict
from numbers import Number
from viur.core.config import conf
from viur.core.bones.base import BaseBone, ReadFromClientError, ReadFromClientErrorSeverity
from viur.core.i18n import translate

if t.TYPE_CHECKING:
    from viur.core.skeleton import SkeletonInstance

SelectBoneValue = t.Union[str, Number, enum.Enum]
"""
Type alias of possible values in a SelectBone. SelectBoneValue can be either a string (str) or a number (Number)
"""

SelectBoneMultiple = list[SelectBoneValue]
"""Type alias for values of a multiple SelectBone."""


def translation_key_prefix_skeleton_bonename(bones_instance: BaseBone) -> str:
    """Generate a translation key prefix based on the skeleton and bone name"""
    return f'skeleton.{bones_instance.skel_cls.__name__.lower().removesuffix("skel")}.{bones_instance.name}.'


def translation_key_prefix_bonename(bones_instance: BaseBone) -> str:
    """Generate a translation key prefix based on the bone name"""
    return f'bone.{bones_instance.name}.'


class SelectBone(BaseBone):
    """
    A SelectBone is a bone which can take a value from a certain list of values.
    Inherits from the BaseBone class. The `type` attribute is set to "select".
    """
    type = "select"

    def __init__(
        self,
        *,
        defaultValue: t.Union[
            SelectBoneValue,
            SelectBoneMultiple,
            t.Dict[str, t.Union[SelectBoneMultiple, SelectBoneValue]],
            t.Callable[["SkeletonInstance", t.Self], t.Any],
        ] = None,
        values: dict | list | tuple | t.Callable | enum.EnumMeta = (),
        translation_key_prefix: str | t.Callable[[t.Self], str] = "",
        add_missing_translations: bool = False,
        **kwargs
    ):
        """
        Initializes a new SelectBone.

        :param defaultValue: key(s) of the values which will be checked by default.
        :param values: dict of key->value pairs from which the user can choose from
            -- or a callable that returns a dict.
        :param translation_key_prefix: A prefix for the key of the translation object.
            It is empty by default, so that only the label (dict value) from the values is used.
            A static string or dynamic method can be used (like `translation_key_prefix_bonename`).
        :param kwargs: Additional keyword arguments that will be passed to the superclass' __init__ method.
        """
        super().__init__(defaultValue=defaultValue, **kwargs)
        self.translation_key_prefix = translation_key_prefix
        self.add_missing_translations = add_missing_translations

        # handle list/tuple as dicts
        if isinstance(values, (list, tuple)):
            values = {value: value for value in values}

        assert isinstance(values, (dict, OrderedDict)) or callable(values)
        self._values = values

    def __getattribute__(self, item):
        """
        Overrides the default __getattribute__ method to handle the 'values' attribute dynamically. If the '_values'
        attribute is callable, it will be called and the result will be stored in the 'values' attribute.

        :param str item: The attribute name.
        :return: The value of the specified attribute.

        :raises AssertionError: If the resulting values are not of type dict or OrderedDict.
        """
        if item == "values":
            values = self._values
            if isinstance(values, enum.EnumMeta):
                values = {value.value: value.name for value in values}
            elif callable(values):
                values = values()

                # handle list/tuple as dicts
                if isinstance(values, (list, tuple)):
                    values = {value: value for value in values}

                assert isinstance(values, (dict, OrderedDict))

            prefix = self.translation_key_prefix
            if callable(prefix):
                prefix = prefix(self)

            values = {
                key: label if isinstance(label, translate) else translate(
                    f"{prefix}{key}", str(label),
                    f"value {key} for {self.name}<{type(self).__name__}> "
                    + f"in {self.skel_cls.__name__} in {self.skel_cls}",
                    add_missing=self.add_missing_translations,
                )
                for key, label in values.items()
            }

            return values

        return super().__getattribute__(item)

    def singleValueUnserialize(self, val):
        if isinstance(self._values, enum.EnumMeta):
            for value in self._values:
                if value.value == val:
                    return value
        return val

    def singleValueSerialize(self, val, skel: 'SkeletonInstance', name: str, parentIndexed: bool):
        if isinstance(self._values, enum.EnumMeta) and isinstance(val, self._values):
            return val.value
        return val

    def singleValueFromClient(self, value, skel, bone_name, client_data):
        if isinstance(self._values, enum.EnumMeta) and isinstance(value, self._values):
            return value, None

        value = str(value)
        if not value:
            return self.getEmptyValue(), [ReadFromClientError(ReadFromClientErrorSeverity.Empty, "No value selected")]

        for key in self.values.keys():
            if str(key) == value:
                if isinstance(self._values, enum.EnumMeta):
                    return self._values(key), None

                return key, None

        return self.getEmptyValue(), [
            ReadFromClientError(ReadFromClientErrorSeverity.Invalid, "Invalid value selected")
        ]

    def structure(self) -> dict:
        return super().structure() | {
            "values":
                {k: str(v) for k, v in self.values.items()}  # new-style dict
                if "bone.select.structure.values.keytuple" not in conf.compatibility
                else [(k, str(v)) for k, v in self.values.items()]  # old-style key-tuple
        }
