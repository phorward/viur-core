# -*- coding: utf-8 -*-

from server.render.json.default import DefaultRender as default
from server.render.json.user import UserRender as user
from server.render.json.file import FileRender as file
from server import conf
from server.utils import createSecurityKey
import datetime, json

__all__=[ default ]

def skey( *args,  **kwargs ):
	return json.dumps( createSecurityKey() ) 
skey.exposed=True

def timestamp( *args, **kwargs):
	d = datetime.datetime.now()
	return( json.dumps( d.strftime("%Y-%m-%dT%H-%M-%S") ) )
timestamp.exposed=True

def generateAdminConfig( adminTree ):
	res = {}
	for key in dir( adminTree ):
		app = getattr( adminTree, key )
		if "adminInfo" in dir( app ) and app.adminInfo:
			res[ key ] = app.adminInfo
	return( res )
	
def dumpConfig( adminConfig ):
	res = {	"capabilities": conf["viur.capabilities"], 
			"modules": adminConfig, 
			"configuration": {}
		}
	for k, v in conf.items():
		if k.lower().startswith("admin."):
			res["configuration"][ k[ 6: ] ] = v
	return json.dumps( res )

def _postProcessAppObj( obj ):
	obj.skey = skey
	obj.timestamp = timestamp
	adminConfig = generateAdminConfig( obj )
	tmp = lambda *args, **kwargs: dumpConfig( adminConfig )
	tmp.exposed=True
	obj.config = tmp
	return obj