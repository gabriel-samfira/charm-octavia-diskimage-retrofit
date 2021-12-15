# Copyright 2019 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from unittest import mock
import os
import subprocess

import charms_openstack.test_utils as test_utils

import charm.openstack.octavia_diskimage_retrofit as octavia_diskimage_retrofit


class TestOctaviaDiskimageRetrofitCharm(test_utils.PatchHelper):

    def setUp(self):
        super().setUp()
        self.patch_release(
            octavia_diskimage_retrofit.OctaviaDiskimageRetrofitCharm.release)
        self.patch_object(octavia_diskimage_retrofit.ch_core.hookenv, 'config')
        self.config.side_effect = lambda: {
            'use-internal-endpoints': False,
        }
        self.target = (
            octavia_diskimage_retrofit.OctaviaDiskimageRetrofitCharm())

    def patch_target(self, attr, return_value=None):
        mocked = mock.patch.object(self.target, attr)
        self._patches[attr] = mocked
        started = mocked.start()
        started.return_value = return_value
        self._patches_start[attr] = started
        setattr(self, attr, started)

    def test_application_version(self):
        self.patch_object(
            octavia_diskimage_retrofit.charms_openstack.charm.core,
            'get_snap_version')
        self.get_snap_version.return_value = 'fake-version'
        c = octavia_diskimage_retrofit.OctaviaDiskimageRetrofitCharm()
        self.assertEqual(c.application_version, 'fake-version')
        self.get_snap_version.assert_called_once_with(
            'octavia-diskimage-retrofit')

    def test_request_credentials(self):
        keystone_endpoint = mock.MagicMock()
        c = octavia_diskimage_retrofit.OctaviaDiskimageRetrofitCharm()
        c.request_credentials(keystone_endpoint)
        keystone_endpoint.request_credentials.assert_called_once_with(
            c.name,
            project='services',
            domain='service_domain')

    def test_get_ubuntu_release(self):
        self.patch_object(
            octavia_diskimage_retrofit.subprocess, 'check_output')
        self.check_output.return_value = '20.04 LTS\n'
        self.assertEquals(self.target.get_ubuntu_release(), '20.04')
        self.check_output.assert_called_once_with(
            ['distro-info', '-r', '--lts'], universal_newlines=True)
        self.check_output.reset_mock()
        self.target.get_ubuntu_release(series='focal')
        self.check_output.assert_called_once_with(
            ['distro-info', '-r', '--series', 'focal'],
            universal_newlines=True)

    def test_retrofit(self):
        self.patch_object(octavia_diskimage_retrofit, 'glance_retrofitter')
        glance = mock.MagicMock()
        self.glance_retrofitter.get_glance_client.return_value = glance

        class FakeImage(object):
            id = 'aId'
            name = 'aName'
            architecture = 'aArchitecture'
            os_distro = 'aOSDistro'
            os_version = 'aOSVersion'
            version_name = 'aVersionName'
            product_name = 'aProductName'
        fake_image = FakeImage()

        self.patch_object(octavia_diskimage_retrofit.os, 'environ')
        self.environ.copy.return_value = {
            'LANG': 'en_US.UTF-8',
            'USER': 'someone',
        }

        proxy_envvars = {
            'http_proxy': 'http://squid.internal:3128',
            'HTTP_PROXY': 'http://squid.internal:3128',
            'no_proxy': 'jujucharms.com',
            'NO_PROXY': 'jujucharms.com',
        }

        glance.images.create.return_value = fake_image
        self.glance_retrofitter.find_source_image.return_value = fake_image
        self.patch_object(
            octavia_diskimage_retrofit.tempfile,
            'NamedTemporaryFile')
        self.patch_object(octavia_diskimage_retrofit.ch_core, 'hookenv')
        self.patch_object(octavia_diskimage_retrofit.subprocess,
                          'check_output')
        self.patch_target('config')
        self.config.__getitem__ = lambda _, key: {
            'debug': True,
            'retrofit-series': '',
            'retrofit-uca-pocket': 'pocket',
            'amp-image-tag': 'octavia-amphora',
        }.get(key)
        self.patch_target('get_ubuntu_release')
        self.get_ubuntu_release.side_effect = lambda series: (
            '20.04' if series == 'focal' else '18.04')
        self.patch_object(octavia_diskimage_retrofit.ch_core.host,
                          'get_distrib_codename')
        self.get_distrib_codename.return_value = 'charm-unit-distro'
        with mock.patch('charm.openstack.octavia_diskimage_retrofit.open',
                        create=True) as mocked_open:
            self.glance_retrofitter.find_destination_image.return_value = \
                [fake_image]
            with self.assertRaises(
                    octavia_diskimage_retrofit.DestinationImageExists):
                self.target.retrofit('aKeystone')
                _fsi_mock = self.glance_retrofitter.find_source_image
                _fsi_mock.assert_called_once_with(
                    mock.ANY, release='20.04')
            self.get_ubuntu_release.assert_has_calls([
                mock.call(series=''),
                mock.call(series='charm-unit-distro'),
            ])
            self.get_ubuntu_release.reset_mock()
            self.config.__getitem__ = lambda _, key: {
                'debug': True,
                'retrofit-series': 'bionic',
                'retrofit-uca-pocket': '',
                'amp-image-tag': 'octavia-amphora',
            }.get(key)
            self.glance_retrofitter.find_source_image.reset_mock()
            self.glance_retrofitter.session_from_identity_credentials.\
                assert_called_once_with('aKeystone')
            self.glance_retrofitter.get_glance_client.assert_called_once_with(
                self.glance_retrofitter.session_from_identity_credentials(),
                endpoint_type='publicURL')
            self.glance_retrofitter.find_destination_image.return_value = \
                []
            self.hookenv.env_proxy_settings.return_value = proxy_envvars
            self.target.retrofit('aKeystone')
            self.get_ubuntu_release.assert_called_once_with(series='bionic')

            self.glance_retrofitter.find_source_image.assert_called_once_with(
                mock.ANY, release='18.04')
            self.NamedTemporaryFile.assert_has_calls([
                mock.call(delete=False,
                          dir=octavia_diskimage_retrofit.TMPDIR),
                mock.call(delete=False,
                          dir=octavia_diskimage_retrofit.TMPDIR),
            ])
            self.hookenv.atexit.assert_called_with(os.unlink, mock.ANY)
            self.hookenv.status_set.assert_has_calls([
                mock.call('maintenance', 'Downloading aName'),
                mock.call('maintenance', 'Retrofitting aName'),
                mock.call('maintenance', 'Uploading aName'),
            ])
            self.glance_retrofitter.download_image.assert_called_once_with(
                glance, fake_image, self.NamedTemporaryFile())
            self.check_output.assert_called_once_with(
                ['octavia-diskimage-retrofit', '-u', 'ussuri', '-d',
                 self.NamedTemporaryFile().name,
                 self.NamedTemporaryFile().name],
                stderr=subprocess.STDOUT, universal_newlines=True,
                env={**self.environ.copy(), **proxy_envvars})
            glance.images.create.assert_called_once_with(
                container_format='bare',
                disk_format='qcow2',
                name='amphora-haproxy-aArchitecture-aOSDistro-aOSVersion-'
                     'aVersionName')
            glance.images.upload.assert_called_once_with('aId', mock.ANY)
            mocked_open.assert_called_once_with(
                self.NamedTemporaryFile().name, 'rb')
            glance.images.update.assert_called_once_with(
                'aId',
                source_product_name='aProductName',
                source_version_name='aVersionName',
                tags=['octavia-diskimage-retrofit', 'octavia-amphora'])
