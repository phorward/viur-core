# -*- coding: utf-8 -*-
import time, msgpack
from string import Template
from . import default as DefaultRender

serialize = msgpack.dumps
unserialize = msgpack.unpackb

class UserRender(DefaultRender):  # Render user-data to json

	def login(self, skel, **kwargs):
		if kwargs.get("loginFailed", False):
			return serialize("FAILURE")
		return self.edit(skel, **kwargs)

	def loginChoices(self, authMethods, **kwargs):
		return serialize(list(set([x[0] for x in authMethods])))

	def loginSucceeded(self, msg="OKAY", **kwargs):
		return serialize(msg)

	def logoutSuccess(self, **kwargs):
		return serialize("OKAY")

	def verifySuccess(self, skel, **kwargs):
		return serialize("OKAY")

	def verifyFailed(self, **kwargs):
		return serialize("FAILED")

	def passwdRecoverInfo(self, msg, skel=None, tpl=None, **kwargs):
		if skel:
			return self.edit(skel, **kwargs)

		return serialize(msg)

	def passwdRecover(self, *args, **kwargs):
		return self.edit(*args, **kwargs)