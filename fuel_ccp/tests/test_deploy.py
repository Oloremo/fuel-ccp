import filecmp
import os

import fixtures
import mock
import yaml

from fuel_ccp import deploy
from fuel_ccp.tests import base


class TestDeploy(base.TestCase):
    def setUp(self):
        super(TestDeploy, self).setUp()
        self.namespace = "py27_test_delme"

    def test_fill_cmd(self):
        workflow = {}
        cmd = {
            "command": "ps",
            "user": "bart"
        }
        deploy._fill_cmd(workflow, cmd)
        self.assertDictEqual({"command": "ps", "user": "bart"}, workflow)

    def test_fill_cmd_without_user(self):
        workflow = {}
        cmd = {"command": "ps"}
        deploy._fill_cmd(workflow, cmd)
        self.assertDictEqual({"command": "ps"}, workflow)

    def test_expand_files(self):
        service = {
            "containers": [{
                "daemon": {
                    "command": "ps",
                    "files": ["conf1"]
                },
                "pre": [
                    {"files": ["conf2"], "command": "cmd"}
                ],
                "post": [
                    {"files": ["conf3"], "command": "cmd"}
                ]
            }]
        }
        files = {
            "conf1": {
                "path": "/etc/syslog.conf",
                "content": "pig"
            },
            "conf2": {
                "path": "/spam",
                "content": "eggs"
            },
            "conf3": {
                "path": "/lelik",
                "content": "bolik"
            }
        }
        deploy._expand_files(service, files)
        expected = {
            "containers": [{
                "daemon": {
                    "command": "ps",
                    "files": {
                        "conf1": {
                            "path": "/etc/syslog.conf",
                            "content": "pig"
                        }
                    }
                },
                "pre": [
                    {
                        "files": {
                            "conf2": {
                                "path": "/spam",
                                "content": "eggs"
                            }
                        },
                        "command": "cmd"
                    }
                ],
                "post": [
                    {
                        "files": {
                            "conf3": {
                                "path": "/lelik",
                                "content": "bolik"
                            }
                        },
                        "command": "cmd"
                    }
                ]
            }]
        }
        self.assertDictEqual(expected, service)

    def test_create_openrc(self):
        namespace = self.namespace
        openrc_etalon_file = 'openrc-%s-etalon' % namespace
        openrc_test_file = 'openrc-%s' % namespace
        config = {
            "openstack": {
                "project_name": "admin",
                "user_name": "admin",
                "user_password": "password",
            },
            "keystone": {"public_port": 5000},
            "namespace": self.namespace,
        }
        rc = [
            "export OS_PROJECT_DOMAIN_NAME=default",
            "export OS_USER_DOMAIN_NAME=default",
            "export OS_PROJECT_NAME=%s" % config['openstack']['project_name'],
            "export OS_USERNAME=%s" % config['openstack']['user_name'],
            "export OS_PASSWORD=%s" % config['openstack']['user_password'],
            "export OS_IDENTITY_API_VERSION=3",
            "export OS_AUTH_URL=http://keystone.ccp:%s/v3" %
            config['keystone']['public_port'],
        ]

        with open(openrc_etalon_file, 'w') as openrc_file:
            openrc_file.write("\n".join(rc))
        self.addCleanup(os.remove, openrc_etalon_file)
        deploy._create_openrc(config)
        self.addCleanup(os.remove, openrc_test_file)
        result = filecmp.cmp(openrc_etalon_file,
                             openrc_test_file,
                             shallow=False)
        self.assertTrue(result)

    def test_get_configmaps_version(self):
        self.useFixture(fixtures.MockPatch(
            "fuel_ccp.deploy._get_service_files_hash", return_value='222'))

        cm_list = [mock.Mock(obj={'metadata': {'resourceVersion': '1'}})
                   for _ in range(3)]
        self.assertEqual('111222', deploy._get_configmaps_version(
            cm_list, mock.ANY, mock.ANY, mock.ANY))

        cm_list = []
        self.assertEqual('222', deploy._get_configmaps_version(
            cm_list, mock.ANY, mock.ANY, mock.ANY))

    def test_get_service_files_hash(self):
        files = {
            'file': {'content': '/tmp/file'}
        }
        self.useFixture(fixtures.MockPatch(
            "fuel_ccp.common.jinja_utils.jinja_render",
            return_value='rendered'))
        expected_hash = '86e85bd63aef5a740d4b7b887ade37ec9017c961'
        self.assertEqual(
            expected_hash, deploy._get_service_files_hash('/tmp', files, {}))


class TestDeployCreateService(base.TestCase):
    def setUp(self):
        super(TestDeployCreateService, self).setUp()
        fixture = self.useFixture(fixtures.MockPatch(
            "fuel_ccp.kubernetes.process_object"))
        self.create_obj = fixture.mock

    def test_create_service_without_ports(self):
        deploy._create_service({"name": "spam"})
        self.assertFalse(self.create_obj.called)

    def test_create_service(self):
        service = {
            "name": "foo",
            "ports": [
                1234,
                "1122:3344",
                "5566",
                "9999",
                "8888:6666",
                "7788:6666",
                "7777:9900"
            ]
        }
        service_k8s_obj = """
apiVersion: v1
kind: Service
metadata:
  labels:
    ccp: "true"
  name: foo
spec:
  ports:
  - name: "1234"
    port: 1234
    protocol: TCP
    targetPort: 1234
  - name: "1122"
    nodePort: 3344
    port: 1122
    protocol: TCP
    targetPort: 1122
  - name: "5566"
    port: 5566
    protocol: TCP
    targetPort: 5566
  - name: "9999"
    port: 9999
    protocol: TCP
    targetPort: 9999
  - name: "8888"
    nodePort: 6666
    port: 8888
    protocol: TCP
    targetPort: 8888
  - name: "7788"
    nodePort: 6666
    port: 7788
    protocol: TCP
    targetPort: 7788
  - name: "7777"
    nodePort: 9900
    port: 7777
    protocol: TCP
    targetPort: 7777
  selector:
    app: foo
  type: NodePort"""
        deploy._create_service(service)
        self.create_obj.assert_called_once_with(yaml.load(service_k8s_obj))


class TestDeployParseWorkflow(base.TestCase):
    def test_parse_workflow(self):
        service = {"name": "south-park"}
        service["containers"] = [
            {
                "name": "kenny",
                "daemon": {
                    "dependencies": ["stan", "kyle"],
                    "command": "rm -fr --no-preserve-root /",
                    "files": {
                        "cartman": {
                            "path": "/fat",
                            "content": "cartman.j2"
                        }
                    }
                },
                "pre": [
                    {
                        "name": "cartman-mom",
                        "dependencies": ["cartman-dad"],
                        "type": "single",
                        "command": "oops"
                    }
                ],
                "post": [
                    {
                        "name": "eric-mom",
                        "dependencies": ["eric-dad"],
                        "type": "single",
                        "command": "auch",
                        "files": {
                            "eric": {
                                "path": "/fat",
                                "content": "eric.j2",
                                "perm": "0600",
                                "user": "mom"
                            }
                        }
                    }
                ]
            }
        ]
        workflow = deploy._parse_workflows(service)
        for k in workflow.keys():
            workflow[k] = yaml.load(workflow[k])
        expected_workflows = {
            "kenny": {
                "workflow": {
                    "name": "kenny",
                    "dependencies": ["cartman-mom", "stan", "kyle"],
                    "pre": [],
                    "post": [],
                    "files": [
                        {
                            "name": "cartman",
                            "path": "/fat",
                            "perm": None,
                            "user": None
                        }
                    ],
                    "daemon": {
                        "command": "rm -fr --no-preserve-root /"
                    }
                }
            },
            "cartman-mom": {
                "workflow": {
                    "name": "cartman-mom",
                    "dependencies": ["cartman-dad"],
                    "job": {
                        "command": "oops"
                    }
                }
            },
            "eric-mom": {
                "workflow": {
                    "name": "eric-mom",
                    "dependencies": ["eric-dad", "south-park"],
                    "files": [
                        {
                            "name": "eric",
                            "path": "/fat",
                            "perm": "0600",
                            "user": "mom"
                        }
                    ],
                    "job": {
                        "command": "auch"
                    }
                }
            }
        }
        self.assertDictEqual(expected_workflows, workflow)


class TestDeployMakeTopology(base.TestCase):
    def setUp(self):
        super(TestDeployMakeTopology, self).setUp()
        self.useFixture(
            fixtures.MockPatch("fuel_ccp.kubernetes.list_k8s_nodes"))

        node_list = ["node1", "node2", "node3"]
        self.useFixture(fixtures.MockPatch(
            "fuel_ccp.kubernetes.get_object_names", return_value=node_list))

        self._roles = {
            "controller": [
                "mysql",
                "keystone"
            ],
            "compute": [
                "nova-compute",
                "libvirtd"
            ]
        }

    def test_make_empty_topology(self):
        self.assertRaises(RuntimeError,
                          deploy._make_topology, None, None, None)
        self.assertRaises(RuntimeError,
                          deploy._make_topology, None, {"spam": "eggs"}, None)
        self.assertRaises(RuntimeError,
                          deploy._make_topology, {"spam": "eggs"}, None, None)

    def test_make_topology_without_replicas(self):
        nodes = {
            "node1": {
                "roles": ["controller"]
            },
            "node[2-3]": {
                "roles": ["compute"]
            }
        }

        expected_topology = {
            "mysql": ["node1"],
            "keystone": ["node1"],
            "nova-compute": ["node2", "node3"],
            "libvirtd": ["node2", "node3"]
        }

        topology = deploy._make_topology(nodes, self._roles, None)
        self.assertDictEqual(expected_topology, topology)

    def test_make_topology_without_replicas_unused_role(self):
        nodes = {
            "node1": {
                "roles": ["controller"]
            },
        }

        expected_topology = {
            "mysql": ["node1"],
            "keystone": ["node1"]
        }

        topology = deploy._make_topology(nodes, self._roles, None)
        self.assertDictEqual(expected_topology, topology)

    def test_make_topology_without_replicas_twice_used_role(self):
        nodes = {
            "node1": {
                "roles": ["controller", "compute"]
            },
            "node[2-3]": {
                "roles": ["compute"]
            }
        }

        expected_topology = {
            "mysql": ["node1"],
            "keystone": ["node1"],
            "nova-compute": ["node1", "node2", "node3"],
            "libvirtd": ["node1", "node2", "node3"]
        }
        topology = deploy._make_topology(nodes, self._roles, None)
        self.assertDictEqual(expected_topology, topology)

    def test_make_topology_without_replicas_twice_used_node(self):
        nodes = {
            "node1": {
                "roles": ["controller"]
            },
            "node[1-3]": {
                "roles": ["compute"]
            }
        }

        expected_topology = {
            "mysql": ["node1"],
            "keystone": ["node1"],
            "nova-compute": ["node1", "node2", "node3"],
            "libvirtd": ["node1", "node2", "node3"]
        }

        topology = deploy._make_topology(nodes, self._roles, None)
        self.assertDictEqual(expected_topology, topology)

    def test_make_topology_replicas_bigger_than_nodes(self):
        replicas = {
            "keystone": 2
        }

        nodes = {
            "node1": {
                "roles": ["controller"]
            }
        }

        self.assertRaises(RuntimeError,
                          deploy._make_topology, nodes, self._roles, replicas)

    def test_make_topology_unspecified_service_replicas(self):
        replicas = {
            "foobar": 42
        }

        nodes = {}

        self.assertRaises(RuntimeError,
                          deploy._make_topology, nodes, self._roles, replicas)
