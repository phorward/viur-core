# -*- coding: utf-8 -*-
from viur.core.bones import baseBone
from viur.core.bones.bone import ReadFromClientError, ReadFromClientErrorSeverity
import logging
from typing import List, Union


class booleanBone(baseBone):
	type = "bool"
	trueStrs = [str(True), u"1", u"yes"]

	@staticmethod
	def generageSearchWidget(target, name="BOOLEAN BONE"):
		return ({"name": name, "target": target, "type": "boolean"})

	def __init__(self, defaultValue=False, *args, **kwargs):
		assert defaultValue in [True, False]
		super(booleanBone, self).__init__(defaultValue=defaultValue, *args, **kwargs)

	def fromClient(self, skel: 'SkeletonInstance', name: str, data: dict) -> Union[None, List[ReadFromClientError]]:
		"""
			Reads a value from the client.
			If this value is valid for this bone,
			store this value and return None.
			Otherwise our previous value is
			left unchanged and an error-message
			is returned.

			:param name: Our name in the skeleton
			:type name: str
			:param data: *User-supplied* request-data
			:type data: dict
			:returns: str or None
		"""
		if not name in data:
			return [ReadFromClientError(ReadFromClientErrorSeverity.NotSet, name, "Field not submitted")]
		value = data[name]
		if str(value) in self.trueStrs:
			value = True
		else:
			value = False
		err = self.isInvalid(value)
		if not err:
			skel[name] = value
			return False
		else:
			return [ReadFromClientError(ReadFromClientErrorSeverity.Empty, name, err)]

	def refresh(self, skel, boneName) -> None:
		"""
			Inverse of serialize. Evaluates whats
			read from the datastore and populates
			this bone accordingly.

			:param name: The property-name this bone has in its Skeleton (not the description!)
			:type name: str
			:param expando: An instance of the dictionary-like db.Entity class
			:type expando: :class:`db.Entity`
			:returns: bool
		"""
		if not isinstance(skel[boneName], bool):
			val = skel[boneName]
			if str(val) in self.trueStrs:
				skel[boneName] = True
			else:
				skel[boneName] = False

	def buildDBFilter(self, name, skel, dbFilter, rawFilter, prefix=None):
		if name in rawFilter:
			val = rawFilter[name]
			if str(val) in self.trueStrs:
				val = True
			else:
				val = False
			return (super(booleanBone, self).buildDBFilter(name, skel, dbFilter, {name: val}, prefix=prefix))
		else:
			return (dbFilter)
