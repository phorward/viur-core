# -*- coding: utf-8 -*-
import msgpack
from viur.core.render.msgpack.default import DefaultRender


class FileRender(DefaultRender):
	def renderUploadComplete(self, *args, **kwargs):
		return (msgpack.dumps("OKAY "))

	def addDirSuccess(self, *args, **kwargs):
		return (msgpack.dumps("OKAY"))