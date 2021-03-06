# Kubos SDK
# Copyright (C) 2016 Kubos Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import docker
import dockerpty
import json
import os
import subprocess
import sys

from . import status_spinner
from docker import Client
from project import get_local_link_file, module_key, target_key, target_mount_dir

container_repo = 'kubostech/kubos-sdk'
container_tag = '0.1.0'

def get_cli():
    if sys.platform.startswith('linux'):
        c = Client(base_url='unix://var/run/docker.sock') #use with docker-engine
    elif sys.platform.startswith('darwin'):
        c = docker.from_env(assert_hostname=False) #use with docker-machine

    check_docker_status(c)
    return c


def check_docker_status(client):
    try:
        client.ping()
    except:
        print >>sys.stderr, 'Error: Unable to communicate with the Docker service. Please ensure this service is running and you have permission to access it.'
        sys.exit(1)


def pass_through(*args):
    python = '/usr/bin/python'
    sdk_script = '/kubos-sdk/kubos-sdk.py'
    arg_list = list(args)
    arg_list.insert(0, python)
    arg_list.insert(1, sdk_script)
    run_container(arg_list)
    if sys.platform.startswith('linux'):
        fix_permissions()


def fix_permissions():
    cwd = os.getcwd()
    userstr = "%s:%s" % (os.getuid(), os.getgid())
    arg_list = list()
    arg_list.insert(0, "chown")
    arg_list.insert(1, userstr)
    arg_list.insert(2, cwd)
    arg_list.insert(3, "-R")
    run_container(arg_list)


def run_container(arg_list):
    cwd = os.getcwd()
    cli = get_cli()
    image_name = "%s:%s" % (container_repo, container_tag)
    container_data = cli.create_container(image=image_name, command=arg_list, working_dir=cwd, tty=True)
    container_id = container_data['Id'].encode('utf8')
    if container_data['Warnings']:
        print "Warnings: ", container_data['Warnings']
    spinner = status_spinner.start_spinner()
    bind_dirs = mount_volumes()
    cli.start(container_id, binds=bind_dirs)

    container_output = cli.attach(container=container_id, stream=True)
    for entry in container_output:
        sys.stdout.write(entry)
    cli.stop(container_id)
    cli.remove_container(container_id)
    status_spinner.stop_spinner(spinner)


def debug(arg_list):
    cwd = os.getcwd()
    cli = get_cli()
    image_name = "%s:%s" % (container_repo, container_tag)
    bind_dirs = mount_volumes()

    container_data = cli.create_container(image=image_name,
                                          command=arg_list,
                                          host_config=cli.create_host_config(
                                              port_bindings={3333:3333},
                                              network_mode='host',
                                              binds=bind_dirs
                                          ),
                                          working_dir=cwd,
                                          tty=True,
                                          stdin_open=True,
                                          ports=[3333])

    container_id = container_data['Id'].encode('utf8')

    if container_data['Warnings']:
        print "Warnings: ", container_data['Warnings']
    if sys.platform.startswith('darwin'):
        darwin_debug(arg_list, bind_dirs)
    else:
        dockerpty.start(cli, container_id)
        cli.stop(container_id)
        cli.remove_container(container_id)


def mount_volumes():
    #mount configuration for linked modules
    cwd = os.getcwd()
    bind_dirs = []
    local_link_file = get_local_link_file()
    if os.path.isfile(local_link_file):
        with open(local_link_file, 'r') as link_file:
            link_data = json.load(link_file)
            module_links = link_data[module_key]
            target_links = link_data[target_key]
        for key in module_links:
            # in the container modules are mounted at their absolute path on the host
            path_spec = '%s:%s' % (module_links[key], module_links[key])
            bind_dirs.append(path_spec)
        for key in target_links:
            target_dir_name = os.path.basename(target_links[key])
            target_path = os.path.join(target_mount_dir, target_dir_name)
            path_spec = '%s:%s' % (target_links[key], target_links[key])
            bind_dirs.append(path_spec)
    cwd_bind = '%s:%s' % (cwd, cwd)
    bind_dirs.append(cwd_bind)
    return bind_dirs


def darwin_debug(command, bind_dirs):
    '''
    Currently docker-py does not correctly support running pseudo terminals into docker containers on mac or linux.
    Dockerpty correctly implements this functionality but only on Linux. For now this builds the full docker CLI 
    command for all mounted volumes and runs the command directly. This is not a long term solution.
    '''
    args = ['docker', 'run', '--rm', '-it']
    volume_fmt = '-v'
    for directory in bind_dirs:
        args.append(volume_fmt)
        args.append(directory)
    image_name = "%s:%s" % (container_repo, container_tag)
    args.append(image_name)
    args = args + command
    subprocess.call(args)

