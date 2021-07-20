# -*- coding: utf-8 -*-
#########################################################
# python
import os, sys, traceback, re, json, threading, time, shutil
from datetime import datetime
# third-party
import requests
# third-party
from flask import request, render_template, jsonify, redirect
from sqlalchemy import or_, and_, func, not_, desc
import lxml.html
from lxml import etree as ET

# sjva 공용
from framework import db, scheduler, path_data, socketio, SystemModelSetting, app, celery
from framework.util import Util
from framework.common.util import headers
from framework.common.plugin import LogicModuleBase, default_route_socketio
from tool_expand import ToolExpandFileProcess

# 패키지
from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

#from lib_metadata.server_util import MetadataServerUtil
#########################################################

class LogicBasic(LogicModuleBase):
    db_default = {
        'basic_db_version' : '1',
        'basic_download_path' : '',
        'basic_interval' : '30',
        'basic_auto_start' : 'False',
        
    }

    def __init__(self, P):
        super(LogicBasic, self).__init__(P, 'setting')
        self.name = 'basic'

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name
        if sub == 'setting':
            job_id = '%s_%s' % (self.P.package_name, self.name)
            arg['scheduler'] = str(scheduler.is_include(job_id))
            arg['is_running'] = str(scheduler.is_running(job_id))
        try:
            return render_template('{package_name}_{module_name}_{sub}.html'.format(package_name=P.package_name, module_name=self.name, sub=sub), arg=arg)
        except:
            return render_template('sample.html', title='%s - %s' % (P.package_name, sub))


    def process_ajax(self, sub, req):
        try:
            if sub == 'web_list':
                return jsonify(ModelJavcensoredItem.web_list(request))
            elif sub == 'db_remove':
                return jsonify(ModelJavcensoredItem.delete_by_id(req.form['id']))
            elif sub == 'filename_test':
                filename = req.form['filename']
                ModelSetting.set('jav_censored_filename_test', filename)
                newfilename = ToolExpandFileProcess.change_filename_censored(filename)
                newfilename = LogicJavCensored.check_newfilename(filename, newfilename, None)
                return jsonify({'ret':'success', 'data':newfilename})

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'exception', 'log':str(e)})

    def scheduler_function(self):
        logger.debug('mmmmmmmmmmmmmmmmmmm')
        #LogicJavCensored.task()
        #return
        if app.config['config']['use_celery']:
            result = LogicJavCensored.task.apply_async()
            result.get()
        else:
            LogicJavCensored.task()

    def reset_db(self):
        db.session.query(ModelJavcensoredItem).delete()
        db.session.commit()
        return True

    #########################################################

    @staticmethod
    @celery.task
    def task():
        while True:
            try:
                total_count = 0
                source = LogicJavCensored.get_path_list('jav_censored_download_path')
                target = LogicJavCensored.get_path_list('jav_censored_target_path')
                if len(source) == 0 or ModelSetting.get('jav_censored_temp_path') == '' or ModelSetting.get('jav_censored_min_size_path') == '':
                    logger.info('Error censored. path info is empty')

                no_censored_path = ModelSetting.get('jav_censored_temp_path')
                for path in source:
                    ToolExpandFileProcess.remove_small_file_and_move_target(path, ModelSetting.get_int('jav_censored_min_size'), small_move_path=ModelSetting.get('jav_censored_min_size_path'))

                
                for path in source:
                    filelist = os.listdir(path.strip())
                    count = len(filelist)
                    total_count += count
                    for idx, filename in enumerate(filelist):
                        logger.debug('%s / %s : filename : %s', idx, count, filename)    
                        file_path = os.path.join(path, filename)
                        if os.path.isdir(file_path):
                            continue
                        
                        newfilename = ToolExpandFileProcess.change_filename_censored(filename)
                        logger.debug('newfilename : %s', newfilename)
                        
                        if newfilename is None: 
                            shutil.move(os.path.join(path, filename), os.path.join(no_censored_path, filename))
                            continue

                        try:
                            entity = ModelJavcensoredItem(path, filename)
                            newfilename = LogicJavCensored.check_newfilename(filename, newfilename, file_path)
                            
                            # 검색용 키워드
                            search_name = ToolExpandFileProcess.change_filename_censored(newfilename)
                            search_name = os.path.splitext(search_name)[0].replace('-', ' ')
                            search_name = re.sub('\s*\[.*?\]', '', search_name).strip()
                            match = re.search(r'(?P<cd>cd\d{1,2})$', search_name) 
                            if match:
                                search_name = search_name.replace(match.group('cd'), '')
                            logger.debug(search_name)
                            

                            censored_use_meta = ModelSetting.get('jav_censored_use_meta')
                            target_folder = None

                            if censored_use_meta == '0':
                                folders = ModelSetting.get('jav_censored_folder_format').format(code=search_name.replace(' ', '-').upper(), label=search_name.split(' ')[0].upper()).split('/')
                                # 첫번째 자식폴더만 타겟에서 찾는다.
                                for tmp in target:
                                    if os.path.exists(os.path.join(tmp.strip(), folders[0])):
                                        target_folder = os.path.join(tmp.strip(), folders[0])
                                        break
                                if target_folder is None:
                                    target_folder = os.path.join(target[0], *folders)
                                entity.move_type = 'normal'
                            else: 
                                #메타 처리   
                                logger.debug(search_name)
                                try:
                                    from metadata import Logic as MetadataLogic
                                    data = MetadataLogic.get_module('jav_censored').search(search_name, all_find=True, do_trans=False)
                                    logger.debug(data)
                                    meta_info = None
                                    folders = None

                                    if len(data) > 0 and data[0]['score'] > 95:
                                        entity.move_type = 'dvd'
                                        meta_info = MetadataLogic.get_module('jav_censored').info(data[0]['code'])
                                        folders = LogicJavCensored.process_forlder_format(entity.move_type, meta_info)
                                        target_folder = ModelSetting.get('jav_censored_meta_dvd_path')
                                    else:
                                        data = MetadataLogic.get_module('jav_censored_ama').search(search_name, all_find=True, do_trans=False)
                                        process_no_meta = False
                                        if data is not None and len(data) > 0 and data[0]['score'] > 95:
                                            entity.move_type = 'ama'
                                            meta_info = MetadataLogic.get_module('jav_censored_ama').info(data[0]['code'])
                                            if meta_info is not None:
                                                folders = LogicJavCensored.process_forlder_format(entity.move_type, meta_info)
                                                target_folder = ModelSetting.get('jav_censored_meta_ama_path')
                                            else:
                                                process_no_meta = True
                                        else:
                                            process_no_meta = True
                                        if process_no_meta:
                                            entity.move_type = 'no_meta'
                                            target_folder = ModelSetting.get('jav_censored_meta_no_path')
                                            folders = LogicJavCensored.process_forlder_format(entity.move_type, search_name)
                                    target_folder = os.path.join(target_folder, *folders)
                                except Exception as e:
                                    logger.debug('Exception:%s', e)
                                    logger.debug(traceback.format_exc())
                            
                            logger.debug('target_folder : %s', target_folder)
                            dest_filepath = os.path.join(target_folder, newfilename)
                            logger.debug('MOVE : %s %s' % (filename, dest_filepath))
                            entity.target_dir = target_folder
                            entity.target_filename = newfilename

                            if not os.path.exists(target_folder):
                                os.makedirs(target_folder)    

                            if os.path.exists(dest_filepath):
                                logger.debug('EXISTS : %s', dest_filepath)
                                os.remove(file_path)
                                entity.move_type += '_already_exist'
                                
                            if os.path.exists(file_path):
                                shutil.move(os.path.join(path, filename), dest_filepath)

                            if (entity.move_type == 'dvd' or entity.move_type == 'ama') and ModelSetting.get_bool('jav_censored_make_nfo'):
                                from lib_metadata.util_nfo import UtilNfo
                                savepath = os.path.join(target_folder, 'movie.nfo')
                                if not os.path.exists(savepath):
                                    ret = UtilNfo.make_nfo_movie(meta_info, output='save', savepath=savepath)
                            #return
                        except Exception as e:
                            logger.debug('Exception:%s', e)
                            logger.debug(traceback.format_exc())
                        finally:
                            entity.save()
            except Exception as e:
                logger.debug('Exception:%s', e)
                logger.debug(traceback.format_exc())
            if total_count == 0:
                logger.debug('file-processing  count is 0. stop.............')
                break
            else:
                logger.debug('file-processing  count is %s. do repeat.................' % total_count)

    @staticmethod
    def process_forlder_format(meta_type, meta_info):
        folders = None
        if meta_type == 'no_meta':
            folders = ModelSetting.get('jav_censored_folder_format').format(
                code=meta_info.replace(' ', '-').upper(), 
                label=meta_info.split(' ')[0].upper(), 
                label_1=meta_info.split(' ')[0].upper()[0]
            ).split('/')
        else:
            studio = meta_info['studio'] if 'studio' in meta_info and meta_info['studio'] is not None and meta_info['studio'] != '' else 'NO_STUDIO'
            code=meta_info['originaltitle']
            label = meta_info['originaltitle'].split('-')[0]
            label_1 = label[0]
            if meta_type == 'dvd':
                if ModelSetting.get('jav_censored_folder_format_actor') != '' and meta_info['actor'] is not None and len(meta_info['actor']) == 1 and meta_info['actor'][0]['originalname'] != meta_info['actor'][0]['name'] and meta_info['actor'][0]['name'] != '':
                    folders = ModelSetting.get('jav_censored_folder_format_actor').format(
                        code=code, 
                        label=label, 
                        actor=meta_info['actor'][0]['name'], 
                        studio=studio,
                        label_1=label_1
                    ).split('/')
            
            if folders is None:
                folders = ModelSetting.get('jav_censored_folder_format').format(
                    code=code, 
                    label=label,
                    studio=studio,
                    label_1=label_1
                ).split('/')
        return folders

    @staticmethod
    def check_newfilename(filename, newfilename, file_path):
        # 이미 파일처리를 한거라면..
        # newfilename 과 filename 이 [] 제외하고 같다면 처리한파일로 보자
        # 그런 파일은 다시 원본파일명 옵션을 적용하지 않아야한다.
        #logger.debug(filename)
        #logger.debug(newfilename)
        # adn-091-uncenrosed.mp4 
        # 같이 시작하더라도 [] 가 없다면... 변경
        # [] 없거나, 시작이 다르면..  완벽히 일치 하지 않으면
        if filename != newfilename and ((filename.find('[') == -1 or filename.find(']') == -1) or not os.path.splitext(filename)[0].startswith(os.path.splitext(newfilename)[0])):
            newfilename = LogicJavCensored.change_filename_censored_by_save_original(filename, newfilename, file_path)
        else:
            # 이미 한번 파일처리를 한것으로 가정하여 변경하지 않는다.
            newfilename = filename
            # 기존에 cd1 [..].mp4 는 []를 제거한다
            match = re.search(r'cd\d(?P<remove>\s\[.*?\])', newfilename)
            if match:
                newfilename = newfilename.replace(match.group('remove'), '')

        logger.debug('%s => %s', filename, newfilename)
        return newfilename


    @staticmethod
    def change_filename_censored_by_save_original(original_filename, new_filename, original_filepath):
        ''' 원본파일명 보존 옵션에 의해 파일명을 변경한다. '''
        try:
            if ModelSetting.get_bool('jav_censored_include_original_filename'):
                new_name, new_ext = os.path.splitext(new_filename)
                part = None
                match = re.search(r'(?P<part>cd\d+)$', new_name)
                if match:
                    # cd1 앞에가 같아야함.
                    return new_filename
                    part = match.group('part')
                    new_name = new_name.replace(part, '')

                ori_name, ori_ext = os.path.splitext(original_filename)
                # 2019-07-30
                ori_name = ori_name.replace('[', '(').replace(']', ')').strip()
                if part is None:
                    option = ModelSetting.get('jav_censored_include_original_filename_option')
                    if option == '0' or original_filepath is None:
                        return '%s [%s]%s' % (new_name, ori_name, new_ext)
                    elif option == '1':
                        return '%s [%s(%s)]%s' % (new_name, ori_name, os.stat(original_filepath).st_size, new_ext)
                    elif option == '2':
                        from framework.util import Util
                        return '%s [%s(%s)]%s' % (new_name, ori_name, Util.sizeof_fmt(os.stat(original_filepath).st_size, suffix='B'), new_ext)
                    return '%s [%s]%s' % (new_name, ori_name, new_ext)
                else:
                    #안씀
                    return '%s [%s] %s%s' % (new_name, ori_name, part, new_ext)
            else:
                return new_filename
        except Exception as exception:
            logger.debug('Exception:%s', exception)
            logger.debug(traceback.format_exc())



    @staticmethod
    def get_path_list(key):
        tmps = ModelSetting.get_list(key, '\n')
        ret = []
        for t in tmps:
            if t.endswith('*'):
                dirname = os.path.dirname(t)
                listdirs = os.listdir(dirname)
                for l in listdirs:
                    ret.append(os.path.join(dirname, l))
            else:
                ret.append(t)
        return ret

















class ModelFileprocessMovieItem(db.Model):
    __tablename__ = '%s_item' % package_name
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = package_name

    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime)
    filename = db.Column(db.String)
    source_dir = db.Column(db.String)
    is_file = db.Column(db.Boolean)
    flag_move = db.Column(db.Boolean)
    target = db.Column(db.String)
    dest_folder_name = db.Column(db.String)
    movie_title = db.Column(db.String)
    movie_id = db.Column(db.String)
    movie_poster = db.Column(db.String)
    movie_more_title = db.Column(db.String)
    movie_more_info = db.Column(db.String)
    json = db.Column(db.JSON)
    
    def __init__(self):
        self.created_time = datetime.now()

        
    def __repr__(self):
        return repr(self.as_dict())

    def as_dict(self):
        ret = {x.name: getattr(self, x.name) for x in self.__table__.columns}
        ret['created_time'] = self.created_time.strftime('%m-%d %H:%M:%S') 
        if self.json is not None:
            ret['json'] = json.loads(ret['json'])
        else:
            ret['json'] = {}
        return ret
    
    @staticmethod
    def save(item):
        try:
            #for item in result_list:
            model = ModelFileprocessMovieItem()
            model.filename = item['name']
            model.source_dir = item['path']
            model.is_file = item['is_file']
            model.flag_move = item['flag_move']
            model.target = item['target']
            model.dest_folder_name = item['dest_folder_name']
            if item['movie'] is not None:
                model.movie_title = item['movie']['title']
                model.movie_id = item['movie']['id']
                if 'more' in item['movie']:
                    model.movie_poster = item['movie']['more']['poster']
                    model.movie_more_title = item['movie']['more']['title']
                    model.movie_more_info = item['movie']['more']['info'][0]
            #if 'guessit' in item: 
            if 'guessit' in item:
                del item['guessit']
            model.json = json.dumps(item)
            db.session.add(model)
            db.session.commit()
            return True
        except Exception as exception: 
            logger.error('Exception:%s', exception)
            logger.error(traceback.format_exc())
            logger.debug(item)
            db.session.rollback()
            logger.debug('ROLLBACK!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
            return False


"""
한국영화
 - 라이브러리 폴더로 이동
외국영화
 - 자막이 있는 경우
 - 자막이 없는 경우

메타검색실패


폴더명생성규칙




"""