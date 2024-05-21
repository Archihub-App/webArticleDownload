from app.utils.PluginClass import PluginClass
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.utils import DatabaseHandler
from flask import request
from celery import shared_task
from dotenv import load_dotenv
from trafilatura import fetch_url
from trafilatura import extract
from trafilatura import extract_metadata
from trafilatura.settings import use_config
import os
from app.api.users.services import has_role

load_dotenv()

mongodb = DatabaseHandler.DatabaseHandler()

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
            
            if 'parent' not in body or not body['parent']:
                return {'msg': 'No se especificó el ID del recurso padre'}, 400
            
            if not self.has_role('admin', current_user) and not self.has_role('processing', current_user):
                return {'msg': 'No tiene permisos suficientes'}, 401

            task = self.bulk.delay(body, current_user)
            self.add_task_to_user(task.id, 'webArticleDownload.download', current_user, 'msg')
            
            return {'msg': 'Se agregó la tarea a la fila de procesamientos'}, 201
        
    def get_settings(self):
        @self.route('/settings/<type>', methods=['GET'])
        @jwt_required()
        def get_settings(type):
            try:
                current_user = get_jwt_identity()

                if not has_role(current_user, 'admin') and not has_role(current_user, 'processing'):
                    return {'msg': 'No tiene permisos suficientes'}, 401
                
                if type == 'all':
                    return self.settings
                elif type == 'settings':
                    return self.settings['settings']
                elif type == 'bulk':
                    from app.api.system.services import get_resources_schema
                    schema = get_resources_schema()
                    metadata = schema['schema']['metadata']

                    metadata_paths = []
                    
                    def get_paths(data, path, tipo):
                        for key in data:
                            if isinstance(data[key], dict):
                                get_paths(data[key], path + key + '.', tipo)
                            elif 'type' in data:
                                if data['type'] in tipo:
                                    path = path[:-1]
                                    metadata_paths.append(path)
                    
                    get_paths(metadata, 'metadata.', ['text'])
                    metadata_paths = metadata_paths[::-1]

                    new_settings = [*self.settings['settings_' + type]]
                    new_settings.append({
                        'type': 'select',
                        'id': 'metadata_title',
                        'label': 'Campo de titulo',
                        'default': 'metadata.firstLevel.title',
                        'options': [{'value': t, 'label': t} for t in metadata_paths],
                        'required': True
                    })

                    new_settings.append({
                        'type': 'select',
                        'id': 'metadata_author',
                        'label': 'Campo de autor',
                        'default': '',
                        'options': [{'value': t, 'label': t} for t in metadata_paths],
                    })

                    new_settings.append({
                        'type': 'select',
                        'id': 'metadata_url',
                        'label': 'URL',
                        'default': '',
                        'options': [{'value': t, 'label': t} for t in metadata_paths],
                    })

                    metadata_paths = []
                    get_paths(metadata, 'metadata.', ['text-area'])
                    metadata_paths = metadata_paths[::-1]

                    new_settings.append({
                        'type': 'select',
                        'id': 'metadata_content',
                        'label': 'Contenido del artículo',
                        'default': '',
                        'options': [{'value': t, 'label': t} for t in metadata_paths],
                    })

                    metadata_paths = []
                    get_paths(metadata, 'metadata.', ['simple-date'])
                    metadata_paths = metadata_paths[::-1]

                    new_settings.append({
                        'type': 'select',
                        'id': 'metadata_publish_date',
                        'label': 'Campo de fecha de publicación',
                        'default': '',
                        'options': [{'value': t, 'label': t} for t in metadata_paths],
                    })
                    return new_settings
                else:
                    return self.settings['settings_' + type]
            except Exception as e:
                print(str(e))
                return {'msg': str(e)}, 500
        
    @shared_task(ignore_result=False, name='webArticleDownload.download')
    def bulk(body, user):
        def modify_dict(d, path, value):
            keys = path.split('.')
            for key in keys[:-1]:
                d = d.setdefault(key, {})
            d[keys[-1]] = value

        newconfig = use_config()
        newconfig.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")

        url = body['url'].split(',')
        for u in url:
            document = fetch_url(u)
            text = extract(document, config=newconfig)
            metadata = extract_metadata(document)
            
            data = {}
            modify_dict(data, 'metadata.firstLevel.title', metadata.title)
            if body['metadata_url'] != '':
                modify_dict(data, body['metadata_url'], metadata.url)
            if body['metadata_content'] != '':
                modify_dict(data, body['metadata_content'], text)
            if body['metadata_publish_date'] != '':
                modify_dict(data, body['metadata_publish_date'], metadata.date)
            if body['metadata_author'] != '':
                modify_dict(data, body['metadata_author'], metadata.author)

            data['post_type'] = body['post_type']
            data['parent'] = [{'id': body['parent']}]
            data['parents'] = [{'id': body['parent']}]

            from app.api.resources.services import create as create_resource
            create_resource(data, user, [])
        
        return 'Se descargaron los artículos web'
    
plugin_info = {
    'name': 'Descarga de artículos web',
    'description': 'Plugin para descargar artículos web y generar versiones para consulta en el gestor documental.',
    'version': '0.1',
    'author': 'Néstor Andrés Peña',
    'type': ['bulk'],
    'settings': {
        'settings_bulk': [
            {
                'type': 'instructions',
                'title': 'Instrucciones',
                'text': 'Este plugin permite descargar textos de diferentes fuentes web. Para ello, se debe ingresar la URL del artículo web que se desea descargar. El plugin descargará el contenido del artículo y lo almacenará en el gestor documental.'
            },
            {
                'type': 'text',
                'id': 'url',
                'label': 'URL del artículo web',
                'placeholder': 'URL del artículo web',
                'required': True
            }
        ]
    }
}