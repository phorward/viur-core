"""
This module contains the base classes for the bones in ViUR. Bones are the fundamental building blocks of
ViUR's data structures, representing the fields and their properties in the entities managed by the
framework. The base classes defined in this module are the foundation upon which specific bone types are
built, such as string, numeric, and date/time bones.
"""

import copy
import dataclasses
import enum
import hashlib
import inspect
import logging
import typing as t
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum

from viur.core import current, db, i18n, utils
from viur.core.config import conf

if t.TYPE_CHECKING:
    from ..skeleton import Skeleton, SkeletonInstance

__system_initialized = False
"""
Initializes the global variable __system_initialized
"""


def setSystemInitialized():
    """
    Sets the global __system_initialized variable to True, indicating that the system is
    initialized and ready for use. This function should be called once all necessary setup
    tasks have been completed. It also iterates over all skeleton classes and calls their
    setSystemInitialized() method.

    Global variables:
        __system_initialized: A boolean flag indicating if the system is initialized.
    """
    global __system_initialized
    from viur.core.skeleton import iterAllSkelClasses

    for skelCls in iterAllSkelClasses():
        skelCls.setSystemInitialized()

    __system_initialized = True

def getSystemInitialized():
    """
    Retrieves the current state of the system initialization by returning the value of the
    global variable __system_initialized.
    """
    global __system_initialized
    return __system_initialized


class ReadFromClientErrorSeverity(Enum):
    """
    ReadFromClientErrorSeverity is an enumeration that represents the severity levels of errors
    that can occur while reading data from the client.
    """
    NotSet = 0
    """No error occurred"""
    InvalidatesOther = 1
    # TODO: what is this error about?
    """The data is valid, for this bone, but in relation to other invalid"""
    Empty = 2
    """The data is empty, but the bone requires a value"""
    Invalid = 3
    """The data is invalid, but the bone requires a value"""


@dataclass
class ReadFromClientError:
    """
    The ReadFromClientError class represents an error that occurs while reading data from the client.
    This class is used to store information about the error, including its severity, an error message,
    the field path where the error occurred, and a list of invalidated fields.
    """
    severity: ReadFromClientErrorSeverity
    """A ReadFromClientErrorSeverity enumeration value representing the severity of the error."""
    errorMessage: str
    """A string containing a human-readable error message describing the issue."""
    fieldPath: list[str] = field(default_factory=list)
    """A list of strings representing the path to the field where the error occurred."""
    invalidatedFields: list[str] = None
    """A list of strings containing the names of invalidated fields, if any."""

    def __str__(self):
        return f"{'.'.join(self.fieldPath)}: {self.errorMessage} [{self.severity.name}]"


class ReadFromClientException(Exception):
    """
    ReadFromClientError as an Exception to raise.
    """

    def __init__(self, errors: ReadFromClientError | t.Iterable[ReadFromClientError]):
        """
        This is an exception holding ReadFromClientErrors.

        :param errors: Either one or an iterable of errors.
        """
        super().__init__()

        # Allow to specifiy a single ReadFromClientError
        if isinstance(errors, ReadFromClientError):
            errors = (ReadFromClientError, )

        self.errors = tuple(error for error in errors if isinstance(error, ReadFromClientError))

        # Disallow ReadFromClientException without any ReadFromClientErrors
        if not self.errors:
            raise ValueError("ReadFromClientException requires for at least one ReadFromClientError")

        # Either show any errors with severity greater ReadFromClientErrorSeverity.NotSet to the Exception notes,
        # or otherwise all errors (all have ReadFromClientErrorSeverity.NotSet then)
        notes_errors = tuple(
            error for error in self.errors if error.severity.value > ReadFromClientErrorSeverity.NotSet.value
        )

        self.add_note("\n".join(str(error) for error in notes_errors or self.errors))


class UniqueLockMethod(Enum):
    """
    UniqueLockMethod is an enumeration that represents different locking methods for unique constraints
    on bones. This is used to specify how the uniqueness of a value or a set of values should be
    enforced.
    """
    SameValue = 1  # Lock this value for just one entry or each value individually if bone is multiple
    """
    Lock this value so that there is only one entry, or lock each value individually if the bone
    is multiple.
    """
    SameSet = 2  # Same Set of entries (including duplicates), any order
    """Lock the same set of entries (including duplicates) regardless of their order."""
    SameList = 3  # Same Set of entries (including duplicates), in this specific order
    """Lock the same set of entries (including duplicates) in a specific order."""


@dataclass
class UniqueValue:  # Mark a bone as unique (it must have a different value for each entry)
    """
    The UniqueValue class represents a unique constraint on a bone, ensuring that it must have a
    different value for each entry. This class is used to store information about the unique
    constraint, such as the locking method, whether to lock empty values, and an error message to
    display to the user if the requested value is already taken.
    """
    method: UniqueLockMethod  # How to handle multiple values (for bones with multiple=True)
    """
    A UniqueLockMethod enumeration value specifying how to handle multiple values for bones with
    multiple=True.
    """
    lockEmpty: bool  # If False, empty values ("", 0) are not locked - needed if unique but not required
    """
    A boolean value indicating if empty values ("", 0) should be locked. If False, empty values are not
    locked, which is needed if a field is unique but not required.
    """
    message: str  # Error-Message displayed to the user if the requested value is already taken
    """
    A string containing an error message displayed to the user if the requested value is already
    taken.
    """


@dataclass
class MultipleConstraints:
    """
    The MultipleConstraints class is used to define constraints on multiple bones, such as the minimum
    and maximum number of entries allowed and whether value duplicates are allowed.
    """
    min: int = 0
    """An integer representing the lower bound of how many entries can be submitted (default: 0)."""
    max: int = 0
    """An integer representing the upper bound of how many entries can be submitted (default: 0 = unlimited)."""
    duplicates: bool = False
    """A boolean indicating if the same value can be used multiple times (default: False)."""
    sorted: bool | t.Callable = False
    """A boolean value or a method indicating if the value must be sorted (default: False)."""
    reversed: bool = False
    """
    A boolean value indicating if sorted values shall be sorted in reversed order (default: False).
    It is only applied when the `sorted`-flag is set accordingly.
    """

class ComputeMethod(Enum):
    Always = 0  # Always compute on deserialization
    Lifetime = 1  # Update only when given lifetime is outrun; value is only being stored when the skeleton is written
    Once = 2  # Compute only once
    OnWrite = 3  # Compute before written


@dataclass
class ComputeInterval:
    method: ComputeMethod = ComputeMethod.Always
    lifetime: timedelta = None  # defines a timedelta until which the value stays valid (`ComputeMethod.Lifetime`)


@dataclass
class Compute:
    fn: callable  # the callable computing the value
    interval: ComputeInterval = field(default_factory=ComputeInterval)  # the value caching interval
    raw: bool = True  # defines whether the value returned by fn is used as is, or is passed through bone.fromClient


class CloneStrategy(enum.StrEnum):
    """Strategy for selecting the value of a cloned skeleton"""

    SET_NULL = enum.auto()
    """Sets the cloned bone value to None."""

    SET_DEFAULT = enum.auto()
    """Sets the cloned bone value to its defaultValue."""

    SET_EMPTY = enum.auto()
    """Sets the cloned bone value to its emptyValue."""

    COPY_VALUE = enum.auto()
    """Copies the bone value from the source skeleton."""

    CUSTOM = enum.auto()
    """Uses a custom-defined logic for setting the cloned value.
    Requires :attr:`CloneBehavior.custom_func` to be set.
    """


class CloneCustomFunc(t.Protocol):
    """Type for a custom clone function assigned to :attr:`CloneBehavior.custom_func`"""

    def __call__(self, skel: "SkeletonInstance", src_skel: "SkeletonInstance", bone_name: str) -> t.Any:
        """Return the value for the cloned bone"""
        ...


@dataclass
class CloneBehavior:
    """Strategy configuration for selecting the value of a cloned skeleton"""

    strategy: CloneStrategy
    """The strategy used to select a value from a cloned skeleton"""

    custom_func: CloneCustomFunc = None
    """custom-defined logic for setting the cloned value
    Only required when :attr:`strategy` is set to :attr:`CloneStrategy.CUSTOM`.
    """

    def __post_init__(self):
        """Validate this configuration."""
        if self.strategy == CloneStrategy.CUSTOM and self.custom_func is None:
            raise ValueError("CloneStrategy is CUSTOM, but custom_func is not set")
        elif self.strategy != CloneStrategy.CUSTOM and self.custom_func is not None:
            raise ValueError("custom_func is set, but CloneStrategy is not CUSTOM")


class BaseBone(object):
    """
    The BaseBone class serves as the base class for all bone types in the ViUR framework.
    It defines the core functionality and properties that all bones should implement.

    :param descr: Textual, human-readable description of that bone. Will be translated.
    :param defaultValue: If set, this bone will be preinitialized with this value
    :param required: If True, the user must enter a valid value for this bone (the viur.core refuses
        to save the skeleton otherwise). If a list/tuple of languages (strings) is provided, these
        language must be entered.
    :param multiple: If True, multiple values can be given. (ie. n:m relations instead of n:1)
    :param searchable: If True, this bone will be included in the fulltext search. Can be used
        without the need of also been indexed.
    :param type_suffix: Allows to specify an optional suffix for the bone-type, for bone customization
    :param vfunc: If given, a callable validating the user-supplied value for this bone.
        This callable must return None if the value is valid, a String containing an meaningful
        error-message for the user otherwise.
    :param readOnly: If True, the user is unable to change the value of this bone. If a value for this
        bone is given along the POST-Request during Add/Edit, this value will be ignored. Its still
        possible for the developer to modify this value by assigning skel.bone.value.
    :param visible: If False, the value of this bone should be hidden from the user. This does
        *not* protect the value from being exposed in a template, nor from being transferred
        to the client (ie to the admin or as hidden-value in html-form)
    :param compute: If set, the bone's value will be computed in the given method.

        .. NOTE::
            The kwarg 'multiple' is not supported by all bones
    """
    type = "hidden"
    isClonedInstance = False

    skel_cls = None
    """Skeleton class to which this bone instance belongs"""

    name = None
    """Name of this bone (attribute name in the skeletons containing this bone)"""

    def __init__(
        self,
        *,
        compute: Compute = None,
        defaultValue: t.Any = None,
        descr: t.Optional[str | i18n.translate] = None,
        getEmptyValueFunc: callable = None,
        indexed: bool = True,
        isEmptyFunc: callable = None,  # fixme: Rename this, see below.
        languages: None | list[str] = None,
        multiple: bool | MultipleConstraints = False,
        params: dict = None,
        readOnly: bool = None,  # fixme: Rename into readonly (all lowercase!) soon.
        required: bool | list[str] | tuple[str] = False,
        searchable: bool = False,
        type_suffix: str = "",
        unique: None | UniqueValue = None,
        vfunc: callable = None,  # fixme: Rename this, see below.
        visible: bool = True,
        clone_behavior: CloneBehavior | CloneStrategy | None = None,
    ):
        """
        Initializes a new Bone.
        """
        self.isClonedInstance = getSystemInitialized()

        # Standard definitions
        self.descr = descr
        self.params = params or {}
        self.multiple = multiple
        self.required = required
        self.readOnly = bool(readOnly)
        self.searchable = searchable
        self.visible = visible
        self.indexed = indexed

        if type_suffix:
            self.type += f".{type_suffix}"

        if isinstance(category := self.params.get("category"), str):
            self.params["category"] = i18n.translate(category, hint=f"category of a <{type(self).__name__}>")

        # Multi-language support
        if not (
            languages is None or
            (isinstance(languages, list) and len(languages) > 0
             and all([isinstance(x, str) for x in languages]))
        ):
            raise ValueError("languages must be None or a list of strings")

        if languages and "__default__" in languages:
            raise ValueError("__default__ is not supported as a language")

        if (
            not isinstance(required, bool)
            and (not isinstance(required, (tuple, list)) or any(not isinstance(value, str) for value in required))
        ):
            raise TypeError(f"required must be boolean or a tuple/list of strings. Got: {required!r}")

        if isinstance(required, (tuple, list)) and not languages:
            raise ValueError("You set required to a list of languages, but defined no languages.")

        if isinstance(required, (tuple, list)) and languages and (diff := set(required).difference(languages)):
            raise ValueError(f"The language(s) {', '.join(map(repr, diff))} can not be required, "
                             f"because they're not defined.")

        if callable(defaultValue):
            # check if the signature of defaultValue can bind two (fictive) parameters.
            try:
                inspect.signature(defaultValue).bind("skel", "bone")  # the strings are just for the test!
            except TypeError:
                raise ValueError(f"Callable {defaultValue=} requires for the parameters 'skel' and 'bone'.")

        self.languages = languages

        # Default value
        # Convert a None default-value to the empty container that's expected if the bone is
        # multiple or has languages
        default = [] if defaultValue is None and self.multiple else defaultValue
        if self.languages:
            if callable(defaultValue):
                self.defaultValue = defaultValue
            elif not isinstance(defaultValue, dict):
                self.defaultValue = {lang: default for lang in self.languages}
            elif "__default__" in defaultValue:
                self.defaultValue = {lang: defaultValue.get(lang, defaultValue["__default__"])
                                     for lang in self.languages}
            else:
                self.defaultValue = defaultValue  # default will have the same value at this point
        else:
            self.defaultValue = default

        # Unique values
        if unique:
            if not isinstance(unique, UniqueValue):
                raise ValueError("Unique must be an instance of UniqueValue")
            if not self.multiple and unique.method.value != 1:
                raise ValueError("'SameValue' is the only valid method on non-multiple bones")

        self.unique = unique

        # Overwrite some validations and value functions by parameter instead of subclassing
        # todo: This can be done better and more straightforward.
        if vfunc:
            self.isInvalid = vfunc  # fixme: why is this called just vfunc, and not isInvalidValue/isInvalidValueFunc?

        if isEmptyFunc:
            self.isEmpty = isEmptyFunc  # fixme: why is this not called isEmptyValue/isEmptyValueFunc?

        if getEmptyValueFunc:
            self.getEmptyValue = getEmptyValueFunc

        if compute:
            if not isinstance(compute, Compute):
                raise TypeError("compute must be an instanceof of Compute")
            if not isinstance(compute.fn, t.Callable):
                raise ValueError("'compute.fn' must be callable")
            # When readOnly is None, handle flag automatically
            if readOnly is None:
                self.readOnly = True
            if not self.readOnly:
                raise ValueError("'compute' can only be used with bones configured as `readOnly=True`")

            if (
                compute.interval.method == ComputeMethod.Lifetime
                and not isinstance(compute.interval.lifetime, timedelta)
            ):
                raise ValueError(
                    f"'compute' is configured as ComputeMethod.Lifetime, but {compute.interval.lifetime=} was specified"
                )
            # If a RelationalBone is computed and raw is False, the unserialize function is called recursively
            # and the value is recalculated all the time. This parameter is to prevent this.
            self._prevent_compute = False

        self.compute = compute

        if clone_behavior is None:  # auto choose
            if self.unique and self.readOnly:
                self.clone_behavior = CloneBehavior(CloneStrategy.SET_DEFAULT)
            else:
                self.clone_behavior = CloneBehavior(CloneStrategy.COPY_VALUE)
            # TODO: Any different setting for computed bones?
        elif isinstance(clone_behavior, CloneStrategy):
            self.clone_behavior = CloneBehavior(strategy=clone_behavior)
        elif isinstance(clone_behavior, CloneBehavior):
            self.clone_behavior = clone_behavior
        else:
            raise TypeError(f"'clone_behavior' must be an instance of Clone, but {clone_behavior=} was specified")

    def __set_name__(self, owner: "Skeleton", name: str) -> None:
        self.skel_cls = owner
        self.name = name

    def setSystemInitialized(self) -> None:
        """
        Can be overridden to initialize properties that depend on the Skeleton system
        being initialized.

        Here, in the BaseBone, we set descr to the bone_name if no descr argument
        was given in __init__ and make sure that it is a :class:i18n.translate` object.
        """
        if self.descr is None:
            # TODO: The super().__setattr__() call is kinda hackish,
            #  but unfortunately viur-core has no *during system initialisation* state
            super().__setattr__("descr", self.name or "")
        if self.descr and isinstance(self.descr, str):
            super().__setattr__(
                "descr",
                i18n.translate(self.descr, hint=f"descr of a <{type(self).__name__}>{self.name}")
            )

    def isInvalid(self, value):
        """
            Checks if the current value of the bone in the given skeleton is invalid.
            Returns None if the value would be valid for this bone, an error-message otherwise.
        """
        return False

    def isEmpty(self, value: t.Any) -> bool:
        """
            Check if the given single value represents the "empty" value.
            This usually is the empty string, 0 or False.

            .. warning:: isEmpty takes precedence over isInvalid! The empty value is always
                valid - unless the bone is required.
                But even then the empty value will be reflected back to the client.

            .. warning:: value might be the string/object received from the user (untrusted
                input!) or the value returned by get
        """
        return not bool(value)

    def getDefaultValue(self, skeletonInstance):
        """
        Retrieves the default value for the bone.

        This method is called by the framework to obtain the default value of a bone when no value
        is provided. Derived bone classes can overwrite this method to implement their own logic for
        providing a default value.

        :return: The default value of the bone, which can be of any data type.
    """
        if callable(self.defaultValue):
            res = self.defaultValue(skeletonInstance, self)
            if self.languages and self.multiple:
                if not isinstance(res, dict):
                    if not isinstance(res, (list, set, tuple)):
                        return {lang: [res] for lang in self.languages}
                    else:
                        return {lang: res for lang in self.languages}
            elif self.languages:
                if not isinstance(res, dict):
                    return {lang: res for lang in self.languages}
            elif self.multiple:
                if not isinstance(res, (list, set, tuple)):
                    return [res]
            return res

        elif isinstance(self.defaultValue, list):
            return self.defaultValue[:]
        elif isinstance(self.defaultValue, dict):
            return self.defaultValue.copy()
        else:
            return self.defaultValue

    def getEmptyValue(self) -> t.Any:
        """
            Returns the value representing an empty field for this bone.
            This might be the empty string for str/text Bones, Zero for numeric bones etc.
        """
        return None

    def __setattr__(self, key, value):
        """
        Custom attribute setter for the BaseBone class.

        This method is used to ensure that certain bone attributes, such as 'multiple', are only
        set once during the bone's lifetime. Derived bone classes should not need to overwrite this
        method unless they have additional attributes with similar constraints.

        :param key: A string representing the attribute name.
        :param value: The value to be assigned to the attribute.

        :raises AttributeError: If a protected attribute is attempted to be modified after its initial
            assignment.
        """
        if not self.isClonedInstance and getSystemInitialized() and key != "isClonedInstance" and not key.startswith(
                "_"):
            raise AttributeError("You cannot modify this Skeleton. Grab a copy using .clone() first")
        super().__setattr__(key, value)

    def collectRawClientData(self, name, data, multiple, languages, collectSubfields):
        """
        Collects raw client data for the bone and returns it in a dictionary.

        This method is called by the framework to gather raw data from the client, such as form data or data from a
        request. Derived bone classes should overwrite this method to implement their own logic for collecting raw data.

        :param name: A string representing the bone's name.
        :param data: A dictionary containing the raw data from the client.
        :param multiple: A boolean indicating whether the bone supports multiple values.
        :param languages: An optional list of strings representing the supported languages (default: None).
        :param collectSubfields: A boolean indicating whether to collect data for subfields (default: False).

        :return: A dictionary containing the collected raw client data.
        """
        fieldSubmitted = False
        if languages:
            res = {}
            for lang in languages:
                if not collectSubfields:
                    if f"{name}.{lang}" in data:
                        fieldSubmitted = True
                        res[lang] = data[f"{name}.{lang}"]
                        if multiple and not isinstance(res[lang], list):
                            res[lang] = [res[lang]]
                        elif not multiple and isinstance(res[lang], list):
                            if res[lang]:
                                res[lang] = res[lang][0]
                            else:
                                res[lang] = None
                else:
                    for key in data.keys():  # Allow setting relations with using, multiple and languages back to none
                        if key == f"{name}.{lang}":
                            fieldSubmitted = True
                    prefix = f"{name}.{lang}."
                    if multiple:
                        tmpDict = {}
                        for key, value in data.items():
                            if not key.startswith(prefix):
                                continue
                            fieldSubmitted = True
                            partKey = key.replace(prefix, "")
                            firstKey, remainingKey = partKey.split(".", maxsplit=1)
                            try:
                                firstKey = int(firstKey)
                            except:
                                continue
                            if firstKey not in tmpDict:
                                tmpDict[firstKey] = {}
                            tmpDict[firstKey][remainingKey] = value
                        tmpList = list(tmpDict.items())
                        tmpList.sort(key=lambda x: x[0])
                        res[lang] = [x[1] for x in tmpList]
                    else:
                        tmpDict = {}
                        for key, value in data.items():
                            if not key.startswith(prefix):
                                continue
                            fieldSubmitted = True
                            partKey = key.replace(prefix, "")
                            tmpDict[partKey] = value
                        res[lang] = tmpDict
            return res, fieldSubmitted
        else:  # No multi-lang
            if not collectSubfields:
                if name not in data:  # Empty!
                    return None, False
                val = data[name]
                if multiple and not isinstance(val, list):
                    return [val], True
                elif not multiple and isinstance(val, list):
                    if val:
                        return val[0], True
                    else:
                        return None, True  # Empty!
                else:
                    return val, True
            else:  # No multi-lang but collect subfields
                for key in data.keys():  # Allow setting relations with using, multiple and languages back to none
                    if key == name:
                        fieldSubmitted = True
                prefix = f"{name}."
                if multiple:
                    tmpDict = {}
                    for key, value in data.items():
                        if not key.startswith(prefix):
                            continue
                        fieldSubmitted = True
                        partKey = key.replace(prefix, "")
                        try:
                            firstKey, remainingKey = partKey.split(".", maxsplit=1)
                            firstKey = int(firstKey)
                        except:
                            continue
                        if firstKey not in tmpDict:
                            tmpDict[firstKey] = {}
                        tmpDict[firstKey][remainingKey] = value
                    tmpList = list(tmpDict.items())
                    tmpList.sort(key=lambda x: x[0])
                    return [x[1] for x in tmpList], fieldSubmitted
                else:
                    res = {}
                    for key, value in data.items():
                        if not key.startswith(prefix):
                            continue
                        fieldSubmitted = True
                        subKey = key.replace(prefix, "")
                        res[subKey] = value
                    return res, fieldSubmitted

    def parseSubfieldsFromClient(self) -> bool:
        """
            Determines whether the function should parse subfields submitted by the client.
            Set to True only when expecting a list of dictionaries to be transmitted.
        """
        return False

    def singleValueFromClient(self, value: t.Any, skel: 'SkeletonInstance',
                              bone_name: str, client_data: dict
                              ) -> tuple[t.Any, list[ReadFromClientError] | None]:
        """Load a single value from a client

        :param value: The single value which should be loaded.
        :param skel: The SkeletonInstance where the value should be loaded into.
        :param bone_name: The bone name of this bone in the SkeletonInstance.
        :param client_data: The data taken from the client,
            a dictionary with usually bone names as key
        :return: A tuple. If the value is valid, the first element is
            the parsed value and the second is None.
            If the value is invalid or not parseable, the first element is a empty value
            and the second a list of *ReadFromClientError*.
        """
        # The BaseBone will not read any client_data in fromClient. Use rawValueBone if needed.
        return self.getEmptyValue(), [
            ReadFromClientError(ReadFromClientErrorSeverity.Invalid, "Will not read a BaseBone fromClient!")]

    def fromClient(self, skel: 'SkeletonInstance', name: str, data: dict) -> None | list[ReadFromClientError]:
        """
        Reads a value from the client and stores it in the skeleton instance if it is valid for the bone.

        This function reads a value from the client and processes it according to the bone's configuration.
        If the value is valid for the bone, it stores the value in the skeleton instance and returns None.
        Otherwise, the previous value remains unchanged, and a list of ReadFromClientError objects is returned.

        :param skel: A SkeletonInstance object where the values should be loaded.
        :param name: A string representing the bone's name.
        :param data: A dictionary containing the raw data from the client.
        :return: None if no errors occurred, otherwise a list of ReadFromClientError objects.
        """
        subFields = self.parseSubfieldsFromClient()
        parsedData, fieldSubmitted = self.collectRawClientData(name, data, self.multiple, self.languages, subFields)
        if not fieldSubmitted:
            return [ReadFromClientError(ReadFromClientErrorSeverity.NotSet, "Field not submitted")]
        errors = []
        isEmpty = True
        filled_languages = set()
        if self.languages and self.multiple:
            res = {}
            for language in self.languages:
                res[language] = []
                if language in parsedData:
                    for idx, singleValue in enumerate(parsedData[language]):
                        if self.isEmpty(singleValue):
                            continue
                        isEmpty = False
                        filled_languages.add(language)
                        parsedVal, parseErrors = self.singleValueFromClient(singleValue, skel, name, data)
                        res[language].append(parsedVal)
                        if isinstance(self.multiple, MultipleConstraints) and self.multiple.sorted:
                            if callable(self.multiple.sorted):
                                res[language] = sorted(
                                    res[language],
                                    key=self.multiple.sorted,
                                    reverse=self.multiple.reversed,
                                )
                            else:
                                res[language] = sorted(res[language], reverse=self.multiple.reversed)
                        if parseErrors:
                            for parseError in parseErrors:
                                parseError.fieldPath[:0] = [language, str(idx)]
                            errors.extend(parseErrors)
        elif self.languages:  # and not self.multiple is implicit - this would have been handled above
            res = {}
            for language in self.languages:
                res[language] = None
                if language in parsedData:
                    if self.isEmpty(parsedData[language]):
                        res[language] = self.getEmptyValue()
                        continue
                    isEmpty = False
                    filled_languages.add(language)
                    parsedVal, parseErrors = self.singleValueFromClient(parsedData[language], skel, name, data)
                    res[language] = parsedVal
                    if parseErrors:
                        for parseError in parseErrors:
                            parseError.fieldPath.insert(0, language)
                        errors.extend(parseErrors)
        elif self.multiple:  # and not self.languages is implicit - this would have been handled above
            res = []
            for idx, singleValue in enumerate(parsedData):
                if self.isEmpty(singleValue):
                    continue
                isEmpty = False
                parsedVal, parseErrors = self.singleValueFromClient(singleValue, skel, name, data)
                res.append(parsedVal)

                if parseErrors:
                    for parseError in parseErrors:
                        parseError.fieldPath.insert(0, str(idx))
                    errors.extend(parseErrors)
            if isinstance(self.multiple, MultipleConstraints) and self.multiple.sorted:
                if callable(self.multiple.sorted):
                    res = sorted(res, key=self.multiple.sorted, reverse=self.multiple.reversed)
                else:
                    res = sorted(res, reverse=self.multiple.reversed)
        else:  # No Languages, not multiple
            if self.isEmpty(parsedData):
                res = self.getEmptyValue()
                isEmpty = True
            else:
                isEmpty = False
                res, parseErrors = self.singleValueFromClient(parsedData, skel, name, data)
                if parseErrors:
                    errors.extend(parseErrors)
        skel[name] = res
        if self.languages and isinstance(self.required, (list, tuple)):
            missing = set(self.required).difference(filled_languages)
            if missing:
                return [ReadFromClientError(ReadFromClientErrorSeverity.Empty, "Field not set", fieldPath=[lang])
                        for lang in missing]
        if isEmpty:
            return [ReadFromClientError(ReadFromClientErrorSeverity.Empty, "Field not set")]

        # Check multiple constraints on demand
        if self.multiple and isinstance(self.multiple, MultipleConstraints):
            errors.extend(self._validate_multiple_contraints(self.multiple, skel, name))

        return errors or None

    def _get_single_destinct_hash(self, value) -> t.Any:
        """
        Returns a distinct hash value for a single entry of this bone.
        The returned value must be hashable.
        """
        return value

    def _get_destinct_hash(self, value) -> t.Any:
        """
        Returns a distinct hash value for this bone.
        The returned value must be hashable.
        """
        if not isinstance(value, str) and isinstance(value, Iterable):
            return tuple(self._get_single_destinct_hash(item) for item in value)

        return value

    def _validate_multiple_contraints(
        self,
        constraints: MultipleConstraints,
        skel: 'SkeletonInstance',
        name: str
    ) -> list[ReadFromClientError]:
        """
        Validates the value of a bone against its multiple constraints and returns a list of ReadFromClientError
        objects for each violation, such as too many items or duplicates.

        :param constraints: The MultipleConstraints definition to apply.
        :param skel: A SkeletonInstance object where the values should be validated.
        :param name: A string representing the bone's name.
        :return: A list of ReadFromClientError objects for each constraint violation.
        """
        res = []
        value = self._get_destinct_hash(skel[name])

        if constraints.min and len(value) < constraints.min:
            res.append(ReadFromClientError(ReadFromClientErrorSeverity.Invalid, "Too few items"))

        if constraints.max and len(value) > constraints.max:
            res.append(ReadFromClientError(ReadFromClientErrorSeverity.Invalid, "Too many items"))

        if not constraints.duplicates:
            if len(set(value)) != len(value):
                res.append(ReadFromClientError(ReadFromClientErrorSeverity.Invalid, "Duplicate items"))

        return res

    def singleValueSerialize(self, value, skel: 'SkeletonInstance', name: str, parentIndexed: bool):
        """
            Serializes a single value of the bone for storage in the database.

            Derived bone classes should overwrite this method to implement their own logic for serializing single
            values.
            The serialized value should be suitable for storage in the database.
        """
        return value

    def serialize(self, skel: 'SkeletonInstance', name: str, parentIndexed: bool) -> bool:
        """
        Serializes this bone into a format that can be written into the datastore.

        :param skel: A SkeletonInstance object containing the values to be serialized.
        :param name: A string representing the property name of the bone in its Skeleton (not the description).
        :param parentIndexed: A boolean indicating whether the parent bone is indexed.
        :return: A boolean indicating whether the serialization was successful.
        """
        self.serialize_compute(skel, name)

        if name in skel.accessedValues:
            newVal = skel.accessedValues[name]
            if self.languages and self.multiple:
                res = db.Entity()
                res["_viurLanguageWrapper_"] = True
                for language in self.languages:
                    res[language] = []
                    if not self.indexed:
                        res.exclude_from_indexes.add(language)
                    if language in newVal:
                        for singleValue in newVal[language]:
                            res[language].append(self.singleValueSerialize(singleValue, skel, name, parentIndexed))
            elif self.languages:
                res = db.Entity()
                res["_viurLanguageWrapper_"] = True
                for language in self.languages:
                    res[language] = None
                    if not self.indexed:
                        res.exclude_from_indexes.add(language)
                    if language in newVal:
                        res[language] = self.singleValueSerialize(newVal[language], skel, name, parentIndexed)
            elif self.multiple:
                res = []

                assert newVal is None or isinstance(newVal, (list, tuple)), \
                    f"Cannot handle {repr(newVal)} here. Expecting list or tuple."

                for singleValue in (newVal or ()):
                    res.append(self.singleValueSerialize(singleValue, skel, name, parentIndexed))

            else:  # No Languages, not Multiple
                res = self.singleValueSerialize(newVal, skel, name, parentIndexed)
            skel.dbEntity[name] = res
            # Ensure our indexed flag is up2date
            indexed = self.indexed and parentIndexed
            if indexed and name in skel.dbEntity.exclude_from_indexes:
                skel.dbEntity.exclude_from_indexes.discard(name)
            elif not indexed and name not in skel.dbEntity.exclude_from_indexes:
                skel.dbEntity.exclude_from_indexes.add(name)
            return True
        return False

    def serialize_compute(self, skel: "SkeletonInstance", name: str) -> None:
        """
        This function checks whether a bone is computed and if this is the case, it attempts to serialize the
        value with the appropriate calculation method

        :param skel: The SkeletonInstance where the current bone is located
        :param name: The name of the bone in the Skeleton
        """
        if not self.compute:
            return None
        match self.compute.interval.method:
            case ComputeMethod.OnWrite:
                skel.accessedValues[name] = self._compute(skel, name)

            case ComputeMethod.Lifetime:
                now = utils.utcNow()

                last_update = \
                    skel.accessedValues.get(f"_viur_compute_{name}_") \
                    or skel.dbEntity.get(f"_viur_compute_{name}_")

                if not last_update or last_update + self.compute.interval.lifetime < now:
                    skel.accessedValues[name] = self._compute(skel, name)
                    skel.dbEntity[f"_viur_compute_{name}_"] = now

            case ComputeMethod.Once:
                if name not in skel.dbEntity:
                    skel.accessedValues[name] = self._compute(skel, name)


    def singleValueUnserialize(self, val):
        """
            Unserializes a single value of the bone from the stored database value.

            Derived bone classes should overwrite this method to implement their own logic for unserializing
            single values. The unserialized value should be suitable for use in the application logic.
        """
        return val

    def unserialize(self, skel: 'viur.core.skeleton.SkeletonInstance', name: str) -> bool:
        """
        Deserialize bone data from the datastore and populate the bone with the deserialized values.

        This function is the inverse of the serialize function. It converts data from the datastore
        into a format that can be used by the bones in the skeleton.

        :param skel: A SkeletonInstance object containing the values to be deserialized.
        :param name: The property name of the bone in its Skeleton (not the description).
        :returns: True if deserialization is successful, False otherwise.
        """
        if name in skel.dbEntity:
            loadVal = skel.dbEntity[name]
        elif (
            # fixme: Remove this piece of sh*t at least with VIUR4
            # We're importing from an old ViUR2 instance - there may only be keys prefixed with our name
            conf.viur2import_blobsource and any(n.startswith(name + ".") for n in skel.dbEntity)
            # ... or computed
            or self.compute
        ):
            loadVal = None
        else:
            skel.accessedValues[name] = self.getDefaultValue(skel)
            return False

        if self.unserialize_compute(skel, name):
            return True

        # unserialize value to given config
        if self.languages and self.multiple:
            res = {}
            if isinstance(loadVal, dict) and "_viurLanguageWrapper_" in loadVal:
                for language in self.languages:
                    res[language] = []
                    if language in loadVal:
                        tmpVal = loadVal[language]
                        if not isinstance(tmpVal, list):
                            tmpVal = [tmpVal]
                        for singleValue in tmpVal:
                            res[language].append(self.singleValueUnserialize(singleValue))
            else:  # We could not parse this, maybe it has been written before languages had been set?
                for language in self.languages:
                    res[language] = []
                mainLang = self.languages[0]
                if loadVal is None:
                    pass
                elif isinstance(loadVal, list):
                    for singleValue in loadVal:
                        res[mainLang].append(self.singleValueUnserialize(singleValue))
                else:  # Hopefully it's a value stored before languages and multiple has been set
                    res[mainLang].append(self.singleValueUnserialize(loadVal))
        elif self.languages:
            res = {}
            if isinstance(loadVal, dict) and "_viurLanguageWrapper_" in loadVal:
                for language in self.languages:
                    res[language] = None
                    if language in loadVal:
                        tmpVal = loadVal[language]
                        if isinstance(tmpVal, list) and tmpVal:
                            tmpVal = tmpVal[0]
                        res[language] = self.singleValueUnserialize(tmpVal)
            else:  # We could not parse this, maybe it has been written before languages had been set?
                for language in self.languages:
                    res[language] = None
                    oldKey = f"{name}.{language}"
                    if oldKey in skel.dbEntity and skel.dbEntity[oldKey]:
                        res[language] = self.singleValueUnserialize(skel.dbEntity[oldKey])
                        loadVal = None  # Don't try to import later again, this format takes precedence
                mainLang = self.languages[0]
                if loadVal is None:
                    pass
                elif isinstance(loadVal, list) and loadVal:
                    res[mainLang] = self.singleValueUnserialize(loadVal)
                else:  # Hopefully it's a value stored before languages and multiple has been set
                    res[mainLang] = self.singleValueUnserialize(loadVal)
        elif self.multiple:
            res = []
            if isinstance(loadVal, dict) and "_viurLanguageWrapper_" in loadVal:
                # Pick one language we'll use
                if conf.i18n.default_language in loadVal:
                    loadVal = loadVal[conf.i18n.default_language]
                else:
                    loadVal = [x for x in loadVal.values() if x is not True]
            if loadVal and not isinstance(loadVal, list):
                loadVal = [loadVal]
            if loadVal:
                for val in loadVal:
                    res.append(self.singleValueUnserialize(val))
        else:  # Not multiple, no languages
            res = None
            if isinstance(loadVal, dict) and "_viurLanguageWrapper_" in loadVal:
                # Pick one language we'll use
                if conf.i18n.default_language in loadVal:
                    loadVal = loadVal[conf.i18n.default_language]
                else:
                    loadVal = [x for x in loadVal.values() if x is not True]
            if loadVal and isinstance(loadVal, list):
                loadVal = loadVal[0]
            if loadVal is not None:
                res = self.singleValueUnserialize(loadVal)

        skel.accessedValues[name] = res
        return True

    def unserialize_compute(self, skel: "SkeletonInstance", name: str) -> bool:
        """
        This function checks whether a bone is computed and if this is the case, it attempts to deserialise the
        value with the appropriate calculation method

        :param skel : The SkeletonInstance where the current Bone is located
        :param name: The name of the Bone in the Skeleton
        :return: True if the Bone was unserialized, False otherwise
        """
        if not self.compute or self._prevent_compute:
            return False

        match self.compute.interval.method:
            # Computation is bound to a lifetime?
            case ComputeMethod.Lifetime:
                now = utils.utcNow()
                from viur.core.skeleton import RefSkel  # noqa: E402 # import works only here because circular imports

                if issubclass(skel.skeletonCls, RefSkel):  # we have a ref skel we must load the complete Entity
                    db_obj = db.Get(skel["key"])
                    last_update = db_obj.get(f"_viur_compute_{name}_")
                else:
                    last_update = skel.dbEntity.get(f"_viur_compute_{name}_")
                    skel.accessedValues[f"_viur_compute_{name}_"] = last_update or now

                if not last_update or last_update + self.compute.interval.lifetime <= now:
                    # if so, recompute and refresh updated value
                    skel.accessedValues[name] = value = self._compute(skel, name)
                    def transact():
                        db_obj = db.Get(skel["key"])
                        db_obj[f"_viur_compute_{name}_"] = now
                        db_obj[name] = value
                        db.Put(db_obj)

                    if db.IsInTransaction():
                        transact()
                    else:
                        db.RunInTransaction(transact)

                    return True

            # Compute on every deserialization
            case ComputeMethod.Always:
                skel.accessedValues[name] = self._compute(skel, name)
                return True

        return False

    def delete(self, skel: 'viur.core.skeleton.SkeletonInstance', name: str):
        """
            Like postDeletedHandler, but runs inside the transaction
        """
        pass

    def buildDBFilter(self,
                      name: str,
                      skel: 'viur.core.skeleton.SkeletonInstance',
                      dbFilter: db.Query,
                      rawFilter: dict,
                      prefix: t.Optional[str] = None) -> db.Query:
        """
            Parses the searchfilter a client specified in his Request into
            something understood by the datastore.
            This function must:

                * - Ignore all filters not targeting this bone
                * - Safely handle malformed data in rawFilter (this parameter is directly controlled by the client)

            :param name: The property-name this bone has in its Skeleton (not the description!)
            :param skel: The :class:`viur.core.db.Query` this bone is part of
            :param dbFilter: The current :class:`viur.core.db.Query` instance the filters should be applied to
            :param rawFilter: The dictionary of filters the client wants to have applied
            :returns: The modified :class:`viur.core.db.Query`
        """
        myKeys = [key for key in rawFilter.keys() if (key == name or key.startswith(name + "$"))]

        if len(myKeys) == 0:
            return dbFilter

        for key in myKeys:
            value = rawFilter[key]
            tmpdata = key.split("$")

            if len(tmpdata) > 1:
                if isinstance(value, list):
                    continue
                if tmpdata[1] == "lt":
                    dbFilter.filter((prefix or "") + tmpdata[0] + " <", value)
                elif tmpdata[1] == "le":
                    dbFilter.filter((prefix or "") + tmpdata[0] + " <=", value)
                elif tmpdata[1] == "gt":
                    dbFilter.filter((prefix or "") + tmpdata[0] + " >", value)
                elif tmpdata[1] == "ge":
                    dbFilter.filter((prefix or "") + tmpdata[0] + " >=", value)
                elif tmpdata[1] == "lk":
                    dbFilter.filter((prefix or "") + tmpdata[0] + " =", value)
                else:
                    dbFilter.filter((prefix or "") + tmpdata[0] + " =", value)
            else:
                if isinstance(value, list):
                    dbFilter.filter((prefix or "") + key + " IN", value)
                else:
                    dbFilter.filter((prefix or "") + key + " =", value)

        return dbFilter

    def buildDBSort(
        self,
        name: str,
        skel: "SkeletonInstance",
        query: db.Query,
        params: dict,
        postfix: str = "",
    ) -> t.Optional[db.Query]:
        """
            Same as buildDBFilter, but this time its not about filtering
            the results, but by sorting them.
            Again: query is controlled by the client, so you *must* expect and safely handle
            malformed data!

            :param name: The property-name this bone has in its Skeleton (not the description!)
            :param skel: The :class:`viur.core.skeleton.Skeleton` instance this bone is part of
            :param dbFilter: The current :class:`viur.core.db.Query` instance the filters should
                be applied to
            :param query: The dictionary of filters the client wants to have applied
            :param postfix: Inherited classes may use this to add a postfix to the porperty name
            :returns: The modified :class:`viur.core.db.Query`,
                None if the query is unsatisfiable.
        """
        if query.queries and (orderby := params.get("orderby")) and utils.string.is_prefix(orderby, name):
            if self.languages:
                lang = None
                if orderby.startswith(f"{name}."):
                    lng = orderby.replace(f"{name}.", "")
                    if lng in self.languages:
                        lang = lng

                if lang is None:
                    lang = current.language.get()
                    if not lang or lang not in self.languages:
                        lang = self.languages[0]

                prop = f"{name}.{lang}"
            else:
                prop = name

            # In case this is a multiple query, check if all filters are valid
            if isinstance(query.queries, list):
                in_eq_filter = None

                for item in query.queries:
                    new_in_eq_filter = [
                        key for key in item.filters.keys()
                        if key.rstrip().endswith(("<", ">", "!="))
                    ]
                    if in_eq_filter and new_in_eq_filter and in_eq_filter != new_in_eq_filter:
                        raise NotImplementedError("Impossible ordering!")

                    in_eq_filter = new_in_eq_filter

            else:
                in_eq_filter = [
                    key for key in query.queries.filters.keys()
                    if key.rstrip().endswith(("<", ">", "!="))
                ]

            if in_eq_filter:
                orderby_prop = in_eq_filter[0].split(" ", 1)[0]
                if orderby_prop != prop:
                    logging.warning(
                        f"The query was rewritten; Impossible ordering changed from {prop!r} into {orderby_prop!r}"
                    )
                    prop = orderby_prop

            query.order((prop + postfix, utils.parse.sortorder(params.get("orderdir"))))

        return query

    def _hashValueForUniquePropertyIndex(
        self,
        value: str | int | float | db.Key | list[str | int | float | db.Key],
    ) -> list[str]:
        """
        Generates a hash of the given value for creating unique property indexes.

        This method is called by the framework to create a consistent hash representation of a value
        for constructing unique property indexes. Derived bone classes should overwrite this method to
        implement their own logic for hashing values.

        :param value: The value(s) to be hashed.

        :return: A list containing a string representation of the hashed value. If the bone is multiple,
                the list may contain more than one hashed value.
        """

        def hashValue(value: str | int | float | db.Key) -> str:
            h = hashlib.sha256()
            h.update(str(value).encode("UTF-8"))
            res = h.hexdigest()
            if isinstance(value, int | float):
                return f"I-{res}"
            elif isinstance(value, str):
                return f"S-{res}"
            elif isinstance(value, db.Key):
                # We Hash the keys here by our self instead of relying on str() or to_legacy_urlsafe()
                # as these may change in the future, which would invalidate all existing locks
                def keyHash(key):
                    if key is None:
                        return "-"
                    return f"{hashValue(key.kind)}-{hashValue(key.id_or_name)}-<{keyHash(key.parent)}>"

                return f"K-{keyHash(value)}"
            raise NotImplementedError(f"Type {type(value)} can't be safely used in an uniquePropertyIndex")

        if not value and not self.unique.lockEmpty:
            return []  # We are zero/empty string and these should not be locked
        if not self.multiple and not isinstance(value, list):
            return [hashValue(value)]
        # We have a multiple bone or multiple values here
        if not isinstance(value, list):
            value = [value]
        tmpList = [hashValue(x) for x in value]
        if self.unique.method == UniqueLockMethod.SameValue:
            # We should lock each entry individually; lock each value
            return tmpList
        elif self.unique.method == UniqueLockMethod.SameSet:
            # We should ignore the sort-order; so simply sort that List
            tmpList.sort()
        # Lock the value for that specific list
        return [hashValue(", ".join(tmpList))]

    def getUniquePropertyIndexValues(self, skel: 'viur.core.skeleton.SkeletonInstance', name: str) -> list[str]:
        """
        Returns a list of hashes for the current value(s) of a bone in the skeleton, used for storing in the
        unique property value index.

        :param skel: A SkeletonInstance object representing the current skeleton.
        :param name: The property-name of the bone in the skeleton for which the unique property index values
                    are required (not the description!).

        :return: A list of strings representing the hashed values for the current bone value(s) in the skeleton.
                If the bone has no value, an empty list is returned.
        """
        val = skel[name]
        if val is None:
            return []
        return self._hashValueForUniquePropertyIndex(val)

    def getReferencedBlobs(self, skel: 'viur.core.skeleton.SkeletonInstance', name: str) -> set[str]:
        """
        Returns a set of blob keys referenced from this bone
        """
        return set()

    def performMagic(self, valuesCache: dict, name: str, isAdd: bool):
        """
            This function applies "magically" functionality which f.e. inserts the current Date
            or the current user.
            :param isAdd: Signals wherever this is an add or edit operation.
        """
        pass  # We do nothing by default

    def postSavedHandler(self, skel: "SkeletonInstance", boneName: str, key: db.Key | None) -> None:
        """
            Can be overridden to perform further actions after the main entity has been written.

            :param boneName: Name of this bone
            :param skel: The skeleton this bone belongs to
            :param key: The (new?) Database Key we've written to. In case of a RelSkel the key is None.
        """
        pass

    def postDeletedHandler(self, skel: 'viur.core.skeleton.SkeletonInstance', boneName: str, key: str):
        """
            Can be overridden to perform  further actions after the main entity has been deleted.

            :param skel: The skeleton this bone belongs to
            :param boneName: Name of this bone
            :param key: The old Database Key of the entity we've deleted
        """
        pass

    def clone_value(self, skel: "SkeletonInstance", src_skel: "SkeletonInstance", bone_name: str) -> None:
        """Clone / Set the value for this bone depending on :attr:`clone_behavior`"""
        match self.clone_behavior.strategy:
            case CloneStrategy.COPY_VALUE:
                try:
                    skel.accessedValues[bone_name] = copy.deepcopy(src_skel.accessedValues[bone_name])
                except KeyError:
                    pass  # bone_name is not in accessedValues, cannot clone it
                try:
                    skel.renderAccessedValues[bone_name] = copy.deepcopy(src_skel.renderAccessedValues[bone_name])
                except KeyError:
                    pass  # bone_name is not in renderAccessedValues, cannot clone it
            case CloneStrategy.SET_NULL:
                skel.accessedValues[bone_name] = None
            case CloneStrategy.SET_DEFAULT:
                skel.accessedValues[bone_name] = self.getDefaultValue(skel)
            case CloneStrategy.SET_EMPTY:
                skel.accessedValues[bone_name] = self.getEmptyValue()
            case CloneStrategy.CUSTOM:
                skel.accessedValues[bone_name] = self.clone_behavior.custom_func(skel, src_skel, bone_name)
            case other:
                raise NotImplementedError(other)

    def refresh(self, skel: 'viur.core.skeleton.SkeletonInstance', boneName: str) -> None:
        """
            Refresh all values we might have cached from other entities.
        """
        pass

    def mergeFrom(self, valuesCache: dict, boneName: str, otherSkel: 'viur.core.skeleton.SkeletonInstance'):
        """
        Merges the values from another skeleton instance into the current instance, given that the bone types match.

        :param valuesCache: A dictionary containing the cached values for each bone in the skeleton.
        :param boneName: The property-name of the bone in the skeleton whose values are to be merged.
        :param otherSkel: A SkeletonInstance object representing the other skeleton from which the values \
            are to be merged.

        This function clones the values from the specified bone in the other skeleton instance into the current
        instance, provided that the bone types match. If the bone types do not match, a warning is logged, and the merge
        is ignored. If the bone in the other skeleton has no value, the function returns without performing any merge
        operation.
        """
        if getattr(otherSkel, boneName) is None:
            return
        if not isinstance(getattr(otherSkel, boneName), type(self)):
            logging.error(f"Ignoring values from conflicting boneType ({getattr(otherSkel, boneName)} is not a "
                          f"instance of {type(self)})!")
            return
        valuesCache[boneName] = copy.deepcopy(otherSkel.valuesCache.get(boneName, None))

    def setBoneValue(self,
                     skel: 'SkeletonInstance',
                     boneName: str,
                     value: t.Any,
                     append: bool,
                     language: None | str = None) -> bool:
        """
        Sets the value of a bone in a skeleton instance, with optional support for appending and language-specific
        values. Sanity checks are being performed.

        :param skel: The SkeletonInstance object representing the skeleton to which the bone belongs.
        :param boneName: The property-name of the bone in the skeleton whose value should be set or modified.
        :param value: The value to be assigned. Its type depends on the type of the bone.
        :param append: If True, the given value is appended to the bone's values instead of replacing it. \
            Only supported for bones with multiple=True.
        :param language: The language code for which the value should be set or appended, \
            if the bone supports languages.

        :return: A boolean indicating whether the operation was successful or not.

        This function sets or modifies the value of a bone in a skeleton instance, performing sanity checks to ensure
        the value is valid. If the value is invalid, no modification occurs. The function supports appending values to
        bones with multiple=True and setting or appending language-specific values for bones that support languages.
        """
        assert not (bool(self.languages) ^ bool(language)), f"language is required or not supported on {boneName!r}"
        assert not append or self.multiple, "Can't append - bone is not multiple"

        if not append and self.multiple:
            # set multiple values at once
            val = []
            errors = []
            for singleValue in value:
                singleValue, singleError = self.singleValueFromClient(singleValue, skel, boneName, {boneName: value})
                val.append(singleValue)
                if singleError:
                    errors.extend(singleError)
        else:
            # set or append one value
            val, errors = self.singleValueFromClient(value, skel, boneName, {boneName: value})

        if errors:
            for e in errors:
                if e.severity in [ReadFromClientErrorSeverity.Invalid, ReadFromClientErrorSeverity.NotSet]:
                    # If an invalid datatype (or a non-parseable structure) have been passed, abort the store
                    logging.error(e)
                    return False
        if not append and not language:
            skel[boneName] = val
        elif append and language:
            if not language in skel[boneName] or not isinstance(skel[boneName][language], list):
                skel[boneName][language] = []
            skel[boneName][language].append(val)
        elif append:
            if not isinstance(skel[boneName], list):
                skel[boneName] = []
            skel[boneName].append(val)
        else:  # Just language
            skel[boneName][language] = val
        return True

    def getSearchTags(self, skel: 'viur.core.skeleton.SkeletonInstance', name: str) -> set[str]:
        """
        Returns a set of strings as search index for this bone.

        This function extracts a set of search tags from the given bone's value in the skeleton
        instance. The resulting set can be used for indexing or searching purposes.

        :param skel: The skeleton instance where the values should be loaded from. This is an instance
            of a class derived from `viur.core.skeleton.SkeletonInstance`.
        :param name: The name of the bone, which is a string representing the key for the bone in
            the skeleton. This should correspond to an existing bone in the skeleton instance.
        :return: A set of strings, extracted from the bone value. If the bone value doesn't have
            any searchable content, an empty set is returned.
        """
        return set()

    def iter_bone_value(
        self, skel: 'viur.core.skeleton.SkeletonInstance', name: str
    ) -> t.Iterator[tuple[t.Optional[int], t.Optional[str], t.Any]]:
        """
        Yield all values from the Skeleton related to this bone instance.

        This method handles multiple/languages cases, which could save a lot of if/elifs.
        It always yields a triplet: index, language, value.
        Where index is the index (int) of a value inside a multiple bone,
        language is the language (str) of a multi-language-bone,
        and value is the value inside this container.
        index or language is None if the bone is single or not multi-lang.

        This function can be used to conveniently iterate through all the values of a specific bone
        in a skeleton instance, taking into account multiple and multi-language bones.

        :param skel: The skeleton instance where the values should be loaded from. This is an instance
            of a class derived from `viur.core.skeleton.SkeletonInstance`.
        :param name: The name of the bone, which is a string representing the key for the bone in
            the skeleton. This should correspond to an existing bone in the skeleton instance.

        :return: A generator which yields triplets (index, language, value), where index is the index
            of a value inside a multiple bone, language is the language of a multi-language bone,
            and value is the value inside this container. index or language is None if the bone is
            single or not multi-lang.
        """
        value = skel[name]
        if not value:
            return None

        if self.languages and isinstance(value, dict):
            for idx, (lang, values) in enumerate(value.items()):
                if self.multiple:
                    if not values:
                        continue
                    for val in values:
                        yield idx, lang, val
                else:
                    yield None, lang, values
        else:
            if self.multiple:
                for idx, val in enumerate(value):
                    yield idx, None, val
            else:
                yield None, None, value

    def _compute(self, skel: 'viur.core.skeleton.SkeletonInstance', bone_name: str):
        """Performs the evaluation of a bone configured as compute"""

        compute_fn_parameters = inspect.signature(self.compute.fn).parameters
        compute_fn_args = {}
        if "skel" in compute_fn_parameters:
            from viur.core.skeleton import skeletonByKind, RefSkel  # noqa: E402 # import works only here because circular imports

            if issubclass(skel.skeletonCls, RefSkel):  # we have a ref skel we must load the complete skeleton
                cloned_skel = skeletonByKind(skel.kindName)()
                if not cloned_skel.read(skel["key"]):
                    raise ValueError(f'{skel["key"]=!r} does no longer exists. Cannot compute a broken relation')
            else:
                cloned_skel = skel.clone()
            cloned_skel[bone_name] = None  # remove value form accessedValues to avoid endless recursion
            compute_fn_args["skel"] = cloned_skel

        if "bone" in compute_fn_parameters:
            compute_fn_args["bone"] = getattr(skel, bone_name)

        if "bone_name" in compute_fn_parameters:
            compute_fn_args["bone_name"] = bone_name

        ret = self.compute.fn(**compute_fn_args)

        def unserialize_raw_value(raw_value: list[dict] | dict | None):
            if self.multiple:
                return [self.singleValueUnserialize(inner_value) for inner_value in raw_value]
            return self.singleValueUnserialize(raw_value)

        if self.compute.raw:
            if self.languages:
                return {
                    lang: unserialize_raw_value(ret.get(lang, [] if self.multiple else None))
                    for lang in self.languages
                }
            return unserialize_raw_value(ret)
        self._prevent_compute = True
        if errors := self.fromClient(skel, bone_name, {bone_name: ret}):
            raise ValueError(f"Computed value fromClient failed with {errors!r}")
        self._prevent_compute = False
        return skel[bone_name]

    def structure(self) -> dict:
        """
        Describes the bone and its settings as an JSON-serializable dict.
        This function has to be implemented for subsequent, specialized bone types.
        """
        ret = {
            "descr": self.descr,
            "type": self.type,
            "required": self.required and not self.readOnly,
            "params": self.params,
            "visible": self.visible,
            "readonly": self.readOnly,
            "unique": self.unique.method.value if self.unique else False,
            "languages": self.languages,
            "emptyvalue": self.getEmptyValue(),
            "indexed": self.indexed,
            "clone_behavior": {
                "strategy": self.clone_behavior.strategy,
            },
        }

        # Provide a defaultvalue, if it's not a function.
        if not callable(self.defaultValue) and self.defaultValue is not None:
            ret["defaultvalue"] = self.defaultValue

        # Provide a multiple setting
        if self.multiple and isinstance(self.multiple, MultipleConstraints):
            ret["multiple"] = {
                "duplicates": self.multiple.duplicates,
                "max": self.multiple.max,
                "min": self.multiple.min,
            }
        else:
            ret["multiple"] = self.multiple

        # Provide compute information
        if self.compute:
            ret["compute"] = {
                "method": self.compute.interval.method.name
            }

            if self.compute.interval.lifetime:
                ret["compute"]["lifetime"] = self.compute.interval.lifetime.total_seconds()

        return ret
