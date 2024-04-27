from app.utils.PluginClass import PluginClass
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.utils import DatabaseHandler
from app.utils import HookHandler
from flask import request
from celery import shared_task
from dotenv import load_dotenv
import os
from app.api.records.models import RecordUpdate
from bson.objectid import ObjectId

load_dotenv()

mongodb = DatabaseHandler.DatabaseHandler()
hookHandler = HookHandler.HookHandler()

USER_FILES_PATH = os.environ.get('USER_FILES_PATH', '')
WEB_FILES_PATH = os.environ.get('WEB_FILES_PATH', '')
ORIGINAL_FILES_PATH = os.environ.get('ORIGINAL_FILES_PATH', '')

class ExtendedPluginClass(PluginClass):
    def __init__(self, path, import_name, name, description, version, author, type, settings):
        super().__init__(path, __file__, import_name, name, description, version, author, type, settings)

    def add_routes(self):
        @self.route('/bulk', methods=['POST'])
        @jwt_required()
        def process_files():
            current_user = get_jwt_identity()
            body = request.get_json()

            if 'post_type' not in body:
                return {'msg': 'No se especificó el tipo de contenido'}, 400
            
            if not self.has_role('admin', current_user) and not self.has_role('processing', current_user):
                return {'msg': 'No tiene permisos suficientes'}, 401

            task = self.bulk.delay(body, current_user)
            self.add_task_to_user(task.id, 'filesProcessing.create_webfile', current_user, 'msg')
            
            return {'msg': 'Se agregó la tarea a la fila de procesamientos'}, 201
        
    @shared_task(ignore_result=False, name='filesProcessing.create_webfile.auto')
    def auto_bulk(self, params):
        return 'ok'
        
    @shared_task(ignore_result=False, name='filesProcessing.create_webfile')
    def bulk(body, user):
        return 'ok'
    
plugin_info = {
    'name': 'Descarga de artículos web',
    'description': 'Plugin para descargar artículos web y generar versiones para consulta en el gestor documental.',
    'version': '0.1',
    'author': 'Néstor Andrés Peña',
    'type': ['lunch'],
    'settings': {
        'settings': [

        ],
        'settings_lunch': []
    }
}