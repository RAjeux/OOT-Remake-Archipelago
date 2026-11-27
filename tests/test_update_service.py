"""Bounded official-release downloads and reversible launcher-only replacement."""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile, ZipInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'client'))
from ootrr_triforce import update_service as updates

sha=lambda raw:hashlib.sha256(raw).hexdigest()


def executable(label=b'new'):
    raw=bytearray(512)
    raw[:2]=b'MZ'
    struct.pack_into('<I',raw,0x3c,128)
    raw[128:132]=b'PE\0\0'
    struct.pack_into('<H',raw,132,0x8664)
    struct.pack_into('<H',raw,152,0x20b)
    struct.pack_into('<H',raw,220,2)
    return bytes(raw)+label


def world(extra=None):
    result=BytesIO()
    with ZipFile(result,'w') as archive:
        archive.writestr(ZipInfo('ootrr_remake/__init__.py',(2026,1,1,0,0,0)),'# synthetic world\n')
        archive.writestr(ZipInfo('ootrr_remake/archipelago.json',(2026,1,1,0,0,0)),'{}')
        if extra:archive.writestr(ZipInfo(extra,(2026,1,1,0,0,0)),b'bad')
    return result.getvalue()


def release(version='2.0.0-alpha.1',date='2026-11-26T10:00:00Z',*,prerelease=True):
    raw_exe,raw_world=executable(),world()
    names={'executable':'OOT-Remake-Archipelago-'+version+'.exe','apworld':'ootrr_remake.apworld'}
    sums=(sha(raw_exe)+'  '+names['executable']+'\n'+sha(raw_world)+'  '+names['apworld']+'\n').encode()
    files={names['executable']:raw_exe,names['apworld']:raw_world,'SHA256SUMS.txt':sums}
    row=dict(tag_name='v'+version,draft=False,prerelease=prerelease,published_at=date,
             html_url='https://github.com/'+updates.REPOSITORY+'/releases/tag/v'+version,body='Synthetic notes.',assets=[])
    responses={}
    for name,raw in files.items():
        url='https://github.com/'+updates.REPOSITORY+'/releases/download/v'+version+'/'+name
        row['assets'].append(dict(name=name,size=len(raw),digest='sha256:'+sha(raw),browser_download_url=url))
        responses[url]=raw
    return row,responses


def checked(rows,current='1.0.0-alpha.1'):
    combined={}
    for _,responses in rows:combined.update(responses)
    def read(url,limit):
        raw=json.dumps([row for row,_ in rows]).encode() if url.startswith(updates.API) else combined[url]
        assert len(raw)<=limit
        return raw
    with patch.object(updates,'_read',side_effect=read):
        return updates.check_for_updates(current_version=current)


class ReleaseTests(unittest.TestCase):
    def test_semver_numeric_prerelease_and_stable_precedence(self):
        for lower,higher in [('0.9.9','0.10.0'),('1.0.0-alpha.9','1.0.0-alpha.10'),
                             ('1.0.0-alpha.10','1.0.0-beta.1'),('1.0.0-rc.1','1.0.0'),
                             ('1.0.0-1','1.0.0-alpha')]:
            self.assertEqual(updates.compare_versions(lower,higher),-1)
        self.assertEqual(updates.compare_versions('v1.0.0+build.2','1.0.0+other'),0)
        for invalid in ('1.2','01.2.3','1.2.3-alpha.01','../../1.2.3','1.2.3-'):
            with self.assertRaises(updates.UpdateError):updates.version_key(invalid)

    def test_newest_publication_wins_over_abandoned_higher_version(self):
        old=release('9.0.0-alpha.1','2026-01-01T10:00:00Z')
        new=release('2.0.0-alpha.1','2026-11-26T10:00:00Z')
        result=checked([old,new])
        self.assertEqual(result['latest_version'],'2.0.0-alpha.1')
        self.assertTrue(result['update_available'])
        self.assertEqual(set(result['assets']),{'executable','apworld','checksums'})

    def test_incomplete_newest_release_never_falls_back(self):
        old=release('9.0.0-alpha.1','2026-01-01T10:00:00Z')
        new=release()
        new[0]['assets'].pop()
        with self.assertRaises(updates.UpdateError) as error:checked([old,new])
        self.assertEqual(error.exception.code,'release_assets')

    def test_stable_channel_excludes_alpha_and_up_to_date_still_has_world_hash(self):
        stable=release('1.0.0','2026-01-01T10:00:00Z',prerelease=False)
        alpha=release('2.0.0-alpha.1')
        result=checked([stable,alpha],current='1.0.0')
        self.assertFalse(result['include_prereleases'])
        self.assertFalse(result['update_available'])
        self.assertEqual(result['assets']['apworld']['sha256'],sha(world()))

    def test_api_digest_and_manifest_must_agree_and_repo_urls_are_exact(self):
        row,responses=release()
        row['assets'][0]['digest']='sha256:'+'0'*64
        with self.assertRaises(updates.UpdateError):checked([(row,responses)])
        row,responses=release()
        row['assets'][0]['browser_download_url']=row['assets'][0]['browser_download_url'].replace(updates.REPOSITORY,'other/repository')
        with self.assertRaises(updates.UpdateError):checked([(row,responses)])

    def test_manifest_supplies_hash_when_api_digest_is_absent(self):
        row,responses=release()
        for asset in row['assets']:asset.pop('digest')
        result=checked([(row,responses)])
        self.assertEqual(result['assets']['executable']['sha256'],sha(executable()))

    def test_redirects_strip_auth_and_refuse_untrusted_hosts(self):
        from urllib.request import Request
        handler=updates._Redirect()
        request=Request('https://github.com/'+updates.REPOSITORY+'/releases/download/v2/a',headers={'Authorization':'private','Cookie':'secret'})
        new=handler.redirect_request(request,None,302,'',{},'https://release-assets.githubusercontent.com/file')
        self.assertFalse(new.has_header('Authorization'))
        self.assertFalse(new.has_header('Cookie'))
        for url in ('http://github.com/file','https://example.com/file','https://github.com:444/file','file:///tmp/exe'):
            with self.assertRaises(updates.UpdateError):handler.redirect_request(request,None,302,'',{},url)

    def test_metadata_reads_are_bounded_and_malformed_json_is_rejected(self):
        with patch.object(updates,'_open',return_value=BytesIO(b'x'*33)):
            with self.assertRaises(updates.UpdateError) as error:updates._read(updates.API+'/releases',32)
        self.assertEqual(error.exception.code,'size')
        for raw in (b'[]',b'null',b'{}',b'not json'):
            with patch.object(updates,'_read',return_value=raw):
                if raw==b'[]':self.assertFalse(updates.check_for_updates('1.0.0')['update_available'])
                else:
                    with self.assertRaises(updates.UpdateError):updates.check_for_updates('1.0.0')

    @unittest.skipUnless(os.name=='nt','Windows process identity')
    def test_windows_process_identity_only_reads_our_own_process(self):
        identity=updates._process_identity(os.getpid())
        self.assertEqual(identity['pid'],os.getpid())
        self.assertGreater(identity['created'],0)
        # Windows venv launchers can redirect to the base Python executable;
        # QueryFullProcessImageName reports that actual process image.
        expected = {Path(sys.executable).resolve(),
                    Path(getattr(sys, '_base_executable', sys.executable)).resolve()}
        self.assertIn(Path(identity['image']), expected)

    def test_reused_process_id_is_not_waited_on(self):
        kernel=Mock()
        kernel.OpenProcess.return_value=987
        parent=dict(pid=101,created=1,image='C:/synthetic.exe')
        with patch.object(updates.ctypes,'WinDLL',return_value=kernel,create=True), \
             patch.object(updates,'_identity_for_handle',return_value=dict(parent,created=2)):
            updates._wait_for_parents({'parents':[parent]})
        kernel.OpenProcess.assert_called_once()
        kernel.WaitForSingleObject.assert_called_once_with(987,0)
        kernel.CloseHandle.assert_called_once_with(987)

    def test_exited_parent_does_not_require_its_unavailable_image_name(self):
        kernel=Mock()
        kernel.OpenProcess.return_value=987
        kernel.WaitForSingleObject.return_value=0
        parent=dict(pid=101,created=1,image='C:/synthetic.exe')
        with patch.object(updates.ctypes,'WinDLL',return_value=kernel,create=True), \
             patch.object(updates,'_identity_for_handle',side_effect=AssertionError('Exited process must not be queried')):
            updates._wait_for_parents({'parents':[parent]})
        kernel.CloseHandle.assert_called_once_with(987)

    def test_parent_exit_during_image_query_is_accepted_only_with_signalled_handle(self):
        parent=dict(pid=101,created=1,image='C:/synthetic.exe')
        for after_query in (0,258):
            with self.subTest(after_query=after_query):
                kernel=Mock()
                kernel.OpenProcess.return_value=987
                kernel.WaitForSingleObject.side_effect=[258,after_query]
                with patch.object(updates.ctypes,'WinDLL',return_value=kernel,create=True), \
                     patch.object(updates,'_identity_for_handle',side_effect=updates.UpdateError('process')):
                    if after_query==0:
                        updates._wait_for_parents({'parents':[parent]})
                    else:
                        with self.assertRaises(updates.UpdateError):
                            updates._wait_for_parents({'parents':[parent]})
                kernel.CloseHandle.assert_called_once_with(987)

    def test_version_reader_uses_system_dll_with_extension_avoiding_version_resource(self):
        library=Mock()
        library.GetFileVersionInfoSizeW.return_value=0
        with patch.object(updates.ctypes,'WinDLL',return_value=library,create=True) as load:
            with self.assertRaises(updates.UpdateError):updates._file_version('synthetic.exe')
        load.assert_called_once_with('version.dll',winmode=0x800,use_last_error=True)


class DownloadAndReplacementTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='update tests é ')
        self.addCleanup(self.folder.cleanup)
        self.home=Path(self.folder.name).resolve()
        self.base=self.home/'app data'
        self.save=self.base/'profiles/room/user/save/progress.sav'
        self.save.parent.mkdir(parents=True)
        self.save.write_bytes(b'unchanged synthetic save')
        self.row,self.responses=release()
        self.release=checked([(self.row,self.responses)])
        version=patch.object(updates,'_file_version',return_value={'ProductName':updates.PRODUCT_NAME,'ProductVersion':'2.0.0-alpha.1'})
        version.start();self.addCleanup(version.stop)

    def download(self):
        with patch.object(updates,'_open',side_effect=lambda url:BytesIO(self.responses[url])):
            return updates.download_update(self.release,base=self.base)

    def schedule(self,download,world_target=None,target_name=None):
        target=self.home/(target_name or 'Portable launcher renamed.exe')
        target.write_bytes(executable(b'old'))
        self.target=target
        def spawn(command,**kwargs):
            path=Path(command[-1]);plan=json.loads(path.read_bytes())
            updates._ready(path,plan)
            return type('Child',(),{'poll':lambda self:None})()
        with patch.object(updates,'can_replace_executable',return_value=True), \
             patch.object(updates,'current_version',return_value='1.0.0-alpha.1'), \
             patch.object(updates.sys,'executable',str(target)), \
             patch.object(updates,'_parent_processes',return_value=[dict(pid=101,created=1,image=str(target))]), \
             patch.object(updates.app_runtime,'spawn_process',side_effect=spawn) as started:
            result=updates.schedule_install(download,base=self.base,world_target=world_target)
        self.assertTrue(result['helper_started'])
        self.assertEqual(started.call_args.args[0][1],'--apply-update')
        self.assertEqual(started.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'],'1')
        return Path(result['plan'])

    def assert_save(self):self.assertEqual(self.save.read_bytes(),b'unchanged synthetic save')

    def test_verified_download_progress_does_not_execute_or_change_user_data(self):
        progress=[]
        with patch.object(updates,'_open',side_effect=lambda url:BytesIO(self.responses[url])), \
             patch.object(updates.app_runtime,'spawn_process',side_effect=AssertionError('Downloading must never execute')):
            result=updates.download_update(self.release,base=self.base,progress=lambda *args:progress.append(args))
        self.assertEqual(Path(result['executable']).read_bytes(),executable())
        self.assertEqual(Path(result['apworld']).read_bytes(),world())
        self.assertEqual(progress[-1][0],100)
        self.assert_save()

    def test_checksum_failure_and_cancel_remove_only_their_staging_files(self):
        damaged=dict(self.responses)
        damaged[self.release['assets']['executable']['url']]=b'x'*self.release['assets']['executable']['size']
        with patch.object(updates,'_open',side_effect=lambda url:BytesIO(damaged[url])):
            with self.assertRaises(updates.UpdateError):updates.download_update(self.release,base=self.base)
        self.assertEqual(list((self.base/'updates').iterdir()),[])
        cancel=threading.Event();cancel.set()
        with self.assertRaises(InterruptedError):updates.download_update(self.release,base=self.base,cancel=cancel)
        self.assertEqual(list((self.base/'updates').iterdir()),[])
        self.assert_save()

    def test_corrupt_executable_and_unsafe_world_are_rejected_before_execution(self):
        too_large=bytearray(world())
        struct.pack_into('<I',too_large,too_large.index(b'PK\x01\x02')+24,(128<<20)+1)
        for raw,validator in [(b'not executable',updates._executable),(world('ootrr_remake/../../escape'),updates._world),
                              (b'not zip',updates._world),(world('unknown/__init__.py'),updates._world),
                              (world('ootrr_remake/ARCHIPELAGO.JSON'),updates._world),(too_large,updates._world)]:
            path=self.home/'invalid';path.write_bytes(raw)
            with self.assertRaises(updates.UpdateError):validator(path)
        self.assertFalse((self.home/'escape').exists())

    @unittest.skipUnless(os.name=='nt','Windows version resources')
    def test_version_resource_must_match_the_product_and_release_version(self):
        path=self.home/'synthetic.exe';path.write_bytes(executable())
        for values in ({'ProductName':'Other product','ProductVersion':'2.0.0-alpha.1'},
                       {'ProductName':updates.PRODUCT_NAME,'ProductVersion':'2.0.0-alpha.2'}):
            with patch.object(updates,'_file_version',return_value=values):
                with self.assertRaises(updates.UpdateError) as error:updates._executable(path,'2.0.0-alpha.1')
                self.assertEqual(error.exception.code,'executable_version')

    def test_success_waits_before_replace_keeps_backup_and_restarts_verified_target(self):
        update=self.download();plan_path=self.schedule(update)
        waited=[];commands=[]
        def wait(plan):
            self.assertEqual(self.target.read_bytes(),executable(b'old'))
            waited.append(True)
        result=updates.apply_update_plan(plan_path,base=self.base,wait_parent=wait,launcher=lambda command:commands.append(command))
        self.assertEqual(waited,[True])
        self.assertEqual(self.target.read_bytes(),executable())
        self.assertEqual(Path(result['backup']).read_bytes(),executable(b'old'))
        self.assertEqual(commands,[[str(self.target),'--complete-update',str(plan_path)]])
        with self.assertRaises(updates.UpdateError):updates.apply_update_plan(plan_path,base=self.base,wait_parent=wait)
        self.assert_save()

    def test_failed_second_replace_or_restart_rolls_back_the_original_executable(self):
        for failure in ('replace','restart'):
            with self.subTest(failure=failure):
                update=self.download();plan_path=self.schedule(update)
                original_replace=updates._replace
                def replace(source,destination,*args,**kwargs):
                    if failure=='replace' and str(source).endswith('.tmp'):raise OSError('synthetic replacement failure')
                    return original_replace(source,destination,*args,**kwargs)
                def launch(command):raise OSError('synthetic startup failure')
                with patch.object(updates,'_replace',side_effect=replace):
                    with self.assertRaises(OSError):
                        updates.apply_update_plan(plan_path,base=self.base,wait_parent=lambda plan:None,launcher=launch)
                self.assertEqual(self.target.read_bytes(),executable(b'old'))
                self.assertEqual(json.loads(plan_path.read_bytes())['state'],'failed')
        self.assert_save()

    def test_target_changes_during_wait_and_plan_path_tampering_never_overwrite_files(self):
        update=self.download();path=self.schedule(update)
        def wait(plan):self.target.write_bytes(executable(b'user changed file'))
        with self.assertRaises(updates.UpdateError):updates.apply_update_plan(path,base=self.base,wait_parent=wait)
        self.assertEqual(self.target.read_bytes(),executable(b'user changed file'))
        plan=json.loads(path.read_bytes());plan['target']=str(self.home/'other.exe');path.write_text(json.dumps(plan))
        with self.assertRaises(updates.UpdateError):updates.apply_update_plan(path,base=self.base,wait_parent=lambda p:None)
        self.assertFalse((self.home/'other.exe').exists())
        self.assert_save()

    def test_cancelled_handshake_cannot_apply_later_and_gui_can_remain_open(self):
        update=self.download()
        target=self.home/'current.exe';target.write_bytes(executable(b'old'))
        with patch.object(updates,'can_replace_executable',return_value=True), \
             patch.object(updates,'current_version',return_value='1.0.0'), \
             patch.object(updates.sys,'executable',str(target)), \
             patch.object(updates,'_parent_processes',return_value=[dict(pid=101,created=1,image=str(target))]), \
             patch.object(updates.app_runtime,'spawn_process'), \
             patch.object(updates,'_await_ready',side_effect=updates.UpdateError('helper_timeout')):
            with self.assertRaises(updates.UpdateError):updates.schedule_install(update,base=self.base)
        path=Path(update['stage'])/'plan.json'
        self.assertEqual(json.loads(path.read_bytes())['state'],'cancelled')
        with self.assertRaises(updates.UpdateError):updates.apply_update_plan(path,base=self.base,wait_parent=lambda p:None)
        self.assertEqual(target.read_bytes(),executable(b'old'))

    def test_cancellation_while_helper_waits_is_rechecked_before_mutation(self):
        update=self.download();path=self.schedule(update)
        def wait(plan):
            plan['state']='cancelled';path.write_text(json.dumps(plan))
        with self.assertRaises(updates.UpdateError):updates.apply_update_plan(path,base=self.base,wait_parent=wait)
        self.assertEqual(self.target.read_bytes(),executable(b'old'))

    def test_ready_handshake_checks_child_failure_and_rejects_invalid_ready_data(self):
        update=self.download();path=self.schedule(update)
        process=Mock();process.poll.return_value=1
        with self.assertRaises(updates.UpdateError) as error:updates._await_ready(process,path,timeout=0)
        self.assertEqual(error.exception.code,'helper_start')
        process.poll.return_value=None
        ready=path.parent/'ready.json'
        for raw in (b'[]',b'{}',b'not json',b'x'*4097):
            ready.write_bytes(raw)
            with self.assertRaises(updates.UpdateError):updates._await_ready(process,path,timeout=0)
        ready.unlink()
        with self.assertRaises(updates.UpdateError) as error:updates._await_ready(process,path,timeout=0)
        self.assertEqual(error.exception.code,'helper_timeout')

    def test_transaction_paths_and_shapes_cannot_redirect_outside_staging(self):
        update=self.download()
        for key,value in (('stage',str(self.home)),('hashes',[]),('executable',None),('apworld','relative.apworld')):
            with self.assertRaises(updates.UpdateError):updates._download(dict(update,**{key:value}),self.base)
        outside=self.home/'outside.exe';outside.write_bytes(executable())
        target=Path(update['executable']);target.unlink()
        try:target.symlink_to(outside)
        except OSError:self.skipTest('Creating file symlinks is not permitted on this host')
        with self.assertRaises(updates.UpdateError):updates._download(update,self.base)
        self.assertEqual(outside.read_bytes(),executable())

    def test_source_mode_and_downgrades_never_schedule_a_replacement(self):
        update=self.download()
        with patch.object(updates,'can_replace_executable',return_value=False), \
             patch.object(updates.app_runtime,'spawn_process') as started:
            with self.assertRaises(updates.UpdateError):updates.schedule_install(update,base=self.base)
        started.assert_not_called()
        with patch.object(updates,'can_replace_executable',return_value=True), \
             patch.object(updates,'current_version',return_value='3.0.0'):
            with self.assertRaises(updates.UpdateError):updates.schedule_install(update,base=self.base)

    def test_world_update_is_independent_and_requires_matching_current_bundle(self):
        update=self.download()
        archipelago=self.home/'Archipelago';(archipelago/'custom_worlds').mkdir(parents=True)
        (archipelago/'ArchipelagoGenerate.exe').touch()
        world_path=archipelago/'custom_worlds/ootrr_remake.apworld';world_path.write_bytes(b'old world')
        status=updates.apworld_status(archipelago,update['hashes']['apworld'])
        self.assertTrue(status['changed'])
        with patch.object(updates.app_runtime,'resource_root',return_value=self.home/'absent'):
            with self.assertRaises(updates.UpdateError):updates.install_world(update,archipelago,base=self.base)
        self.assertEqual(world_path.read_bytes(),b'old world')

    def test_optional_world_failure_keeps_new_launcher_and_completion_is_idempotent(self):
        update=self.download()
        custom=self.home/'Archipelago/custom_worlds';custom.mkdir(parents=True)
        world_path=custom/'ootrr_remake.apworld';world_path.write_bytes(b'old world')
        path=self.schedule(update,world_target=custom,target_name=Path(update['executable']).name)
        updates.apply_update_plan(path,base=self.base,wait_parent=lambda p:None,launcher=lambda command:None)
        with patch.object(updates.sys,'executable',str(self.target)), \
             patch.object(updates,'current_version',return_value=update['version']), \
             patch.object(updates,'install_world',side_effect=OSError('world locked')) as install:
            with self.assertLogs(level='ERROR'):
                result=updates.complete_update(path,base=self.base)
            repeated=updates.complete_update(path,base=self.base)
        self.assertEqual(result,repeated)
        self.assertEqual(install.call_count,1)
        self.assertFalse(result['world_updated'])
        self.assertIn('error_code',result)
        self.assertEqual(self.target.read_bytes(),executable())
        self.assertEqual(world_path.read_bytes(),b'old world')
        self.assert_save()


if __name__=='__main__':unittest.main()
