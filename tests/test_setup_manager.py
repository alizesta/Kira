import unittest
from unittest import mock
import requests
from kira.setup_manager import HardwareProfile,ModelManifest,OllamaSetupManager,SetupError,_model_parts,configured_local_model,registry_manifest
from kira.ollama_client import resolve_model

class Response:
    def __init__(self,payload=None,status=200,lines=()):
        self.payload=payload or {}; self.status_code=status; self.lines=lines
    def raise_for_status(self):
        if self.status_code>=400: raise requests.HTTPError(str(self.status_code))
    def json(self): return self.payload
    def iter_lines(self,decode_unicode=True): yield from self.lines

class SetupManagerTests(unittest.TestCase):
    def test_model_id_parsing(self):
        self.assertEqual(_model_parts("qwen3.5:4b"),("library/qwen3.5","4b"))
        self.assertEqual(_model_parts("team/model:Q4_K_M"),("team/model","Q4_K_M"))
        with self.assertRaises(ValueError): _model_parts("../escape")
    def test_manifest_size_comes_from_registry_layers(self):
        session=mock.Mock(); session.get.return_value=Response({"layers":[{"size":100},{"size":250}]})
        self.assertEqual(registry_manifest("qwen3.5:4b",session=session),ModelManifest("qwen3.5:4b",350,2))
        self.assertIn("/v2/library/qwen3.5/manifests/4b",session.get.call_args.args[0])
    def test_missing_manifest_is_not_zero_size(self):
        session=mock.Mock(); session.get.return_value=Response(status=404)
        with self.assertRaises(SetupError): registry_manifest("not-found",session=session)
    def test_configured_model_alias_resolves_to_installed_runtime_name(self):
        self.assertEqual(resolve_model(["qwen3.5:latest"],"qwen3.5:4b"),"qwen3.5:latest")

    def test_hardware_assessment(self):
        profile=HardwareProfile(ram_bytes=16000,vram_bytes=8000)
        self.assertEqual(profile.assess(7000)[0],"gpu_fit")
        self.assertEqual(profile.assess(10000)[0],"ram_fit")
        self.assertEqual(profile.assess(20000)[0],"constrained")
    def test_start_server_reuses_an_already_running_server(self):
        session=mock.Mock()
        session.get.return_value=Response({"version":"0.6.0"})
        popen=mock.Mock()
        manager=OllamaSetupManager(session=session,popen=popen)
        manager.start_server()
        popen.assert_not_called()

    def test_insufficient_disk_rejects_before_pull(self):
        session=mock.Mock(); session.get.return_value=Response({"layers":[{"size":10000}]})
        manager=OllamaSetupManager(session=session,store_path=__import__("pathlib").Path("models"),
            disk_usage=lambda _p:mock.Mock(free=100))
        with mock.patch("kira.setup_manager._existing_parent",return_value=__import__("pathlib").Path(".")):
            with self.assertRaisesRegex(SetupError,"فضای آزاد کافی نیست"):
                manager.preflight("qwen3.5:4b",profile=HardwareProfile(1000000,None))
        session.post.assert_not_called()
    def test_installed_model_is_not_downloaded_again(self):
        session=mock.Mock(); session.get.return_value=Response({"models":[{"name":"qwen3.5:4b"}]})
        manager=OllamaSetupManager(session=session,selected_model="qwen3.5:4b")
        manager.pull_model("qwen3.5:4b")
        session.post.assert_not_called()
    def test_effective_model_comes_from_canonical_route_not_legacy_mirror(self):
        settings={
            "model":"stale-legacy-model",
            "providers":{"ollama":{"enabled":True,"model":"stale-provider-model"}},
            "routes":[
                {"id":"local-old","provider":"ollama","model":"route-model","enabled":True},
                {"id":"cloud","provider":"groq","model":"cloud-model","enabled":True},
            ],
            "role_route_models":{"surface":["route-model"]},
            "manual_route_id":"cloud",
        }
        self.assertEqual(configured_local_model(settings),"route-model")

    def test_pull_checks_disk_before_requesting_download(self):
        session=mock.Mock()
        session.get.return_value=Response({"models":[]})
        manager=OllamaSetupManager(session=session)
        with mock.patch.object(manager,"preflight",side_effect=SetupError("فضای آزاد کافی نیست")):
            with self.assertRaises(SetupError):
                manager.pull_model("qwen3.5:4b")
        session.post.assert_not_called()

    def test_incomplete_pull_does_not_change_selected_model(self):
        session=mock.Mock()
        session.get.side_effect=[Response({"models":[]}),Response({"models":[]})]
        session.post.return_value=Response(lines=[b'{"status":"downloading","completed":5,"total":10}'])
        manager=OllamaSetupManager(session=session,selected_model="old-model")
        with mock.patch.object(manager,"preflight",return_value=(ModelManifest("new-model",100,1),110,"gpu_fit","ok")):
            with self.assertRaisesRegex(SetupError,"ثبت نشده"):
                manager.pull_model("new-model")
        self.assertEqual(manager.selected_model,"old-model")

    def test_inspection_keeps_connection_and_version_when_model_catalog_fails(self):
        session=mock.Mock()
        session.get.side_effect=[Response({"version":"0.6.0"}),requests.ConnectionError("tags endpoint failed")]
        manager=OllamaSetupManager(session=session,selected_model="qwen3.5:4b",
            executable_finder=lambda _name:"/fake/ollama")
        snapshot=manager.inspect()
        self.assertTrue(snapshot.server_reachable)
        self.assertEqual(snapshot.version,"0.6.0")
        self.assertEqual(snapshot.stages["connection"]["status"],"ready")
        self.assertEqual(snapshot.stages["version"]["status"],"ready")
        self.assertEqual(snapshot.stages["model_catalog"]["status"],"failed")
        self.assertEqual(snapshot.stages["inference"]["status"],"not_tested")

    def test_installed_executable_does_not_mean_server_or_model_is_ready(self):
        session=mock.Mock()
        session.get.side_effect=requests.ConnectionError("offline")
        manager=OllamaSetupManager(session=session,selected_model="qwen3.5:4b",
            executable_finder=lambda _name:"/fake/ollama")
        snapshot=manager.inspect()
        self.assertIsNotNone(snapshot.executable)
        self.assertFalse(snapshot.server_reachable)
        self.assertEqual(snapshot.stages["installation"]["status"],"ready")
        self.assertEqual(snapshot.stages["service"]["status"],"stopped")
        self.assertEqual(snapshot.stages["connection"]["status"],"unreachable")
        self.assertEqual(snapshot.stages["inference"]["status"],"not_tested")

    def test_installed_model_with_failed_inference_is_not_ready(self):
        session=mock.Mock()
        session.get.side_effect=[Response({"version":"0.6.0"}),Response({"models":[{"name":"qwen3.5:4b"}]})]
        manager=OllamaSetupManager(session=session,selected_model="qwen3.5:4b")
        with mock.patch.object(manager,"probe_model",return_value=False):
            snapshot=manager.inspect()
        self.assertTrue(snapshot.selected_model_installed)
        self.assertFalse(snapshot.selected_model_runnable)
        self.assertEqual(snapshot.stages["selected_model"]["status"],"ready")
        self.assertEqual(snapshot.stages["inference"]["status"],"failed")
        self.assertFalse(snapshot.ready)

    def test_install_engine_is_idempotent_when_executable_already_exists(self):
        runner=mock.Mock()
        manager=OllamaSetupManager(executable_finder=lambda _name:"/existing/ollama",runner=runner)
        self.assertEqual(manager.install_engine(),"/existing/ollama")
        runner.assert_not_called()
        self.assertEqual(manager.state_machine.snapshot()["installation"]["status"],"ready")

    def test_pull_accepts_installed_latest_alias_after_download(self):
        session=mock.Mock()
        session.get.side_effect=[Response({"models":[]}),Response({"models":[{"name":"qwen3.5:latest"}]})]
        session.post.return_value=Response(lines=[])
        manager=OllamaSetupManager(session=session)
        with mock.patch.object(manager,"preflight",return_value=(
            ModelManifest("qwen3.5:4b",100,1),110,"gpu_fit","ok")):
            manager.pull_model("qwen3.5:4b")
        self.assertEqual(manager.state_machine.snapshot()["selected_model"]["status"],"ready")

if __name__=="__main__": unittest.main()
