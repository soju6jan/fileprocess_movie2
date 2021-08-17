# -*- coding: utf-8 -*-
#########################################################
# python
import os
import traceback

# third-party
import requests
from flask import Blueprint, request, send_file, redirect

# sjva 공용
from framework import app, path_data, check_api, py_urllib, SystemModelSetting, Util
from framework.logger import get_logger
from framework.util import Util
from plugin import get_model_setting, Logic, default_route, PluginUtil

# 패키지
#########################################################


class P(object):
    package_name = __name__.split('.')[0]
    logger = get_logger(package_name)
    blueprint = Blueprint(package_name, package_name, url_prefix='/%s' %  package_name, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))
    menu = {
        'main' : [package_name, u'영화 v2'],
        'sub' : [
            ['basic', u'파일처리'], ['log', u'로그']
        ], 
        'category' : 'fileprocess',
        'sub2' : {
            'basic' : [
                ['setting', u'설정'], ['list', '처리결과'],
            ],
        }
    }  

    plugin_info = {
        'version' : '0.2.0.0',
        'name' : package_name,
        'category_name' : 'fileprocess',
        'icon' : '',
        'developer' : u'soju6jan',
        'description' : u'파일처리 - 영화 v2',
        'home' : 'https://github.com/soju6jan/%s' % package_name,
        'more' : '',
    }
    ModelSetting = get_model_setting(package_name, logger)
    logic = None
    module_list = None
    home_module = 'basic'


def initialize():
    try:
        app.config['SQLALCHEMY_BINDS'][P.package_name] = 'sqlite:///%s' % (os.path.join(path_data, 'db', '{package_name}.db'.format(package_name=P.package_name)))
        PluginUtil.make_info_json(P.plugin_info, __file__)

        from .logic_basic import LogicBasic
        P.module_list = [LogicBasic(P)]
        P.logic = Logic(P)
        default_route(P)
    except Exception as e: 
        P.logger.error('Exception:%s', e)
        P.logger.error(traceback.format_exc())


initialize()

