from setuptools import setup

dependencies = [
    "multidict==5.1.0",  # Avoid 5.2.0 due to Avast
    "blspy==1.0.7",  # Signature library
    "chiavdf==1.0.3",  # timelord and vdf verification
    "chiabip158==1.0",  # bip158-style wallet filters
    "chiapos==1.0.4",  # proof of space
    "clvm==0.9.7",
    "clvm_rs==0.1.15",
    "clvm_tools==0.4.3",
    "aiohttp==3.7.4",  # HTTP server for full node rpc
    "aiosqlite==0.17.0",  # asyncio wrapper for sqlite, to store blocks
    "bitstring==3.1.9",  # Binary data management library
    "colorama==0.4.4",  # Colorizes terminal output
    "colorlog==5.0.1",  # Adds color to logs
    "concurrent-log-handler==0.9.19",  # Concurrently log and rotate logs
    "cryptography==3.4.7",  # Python cryptography library for TLS - keyring conflict
    "fasteners==0.16.3",  # For interprocess file locking
    "keyring==23.0.1",  # Store keys in MacOS Keychain, Windows Credential Locker
    "keyrings.cryptfile==1.3.4",  # Secure storage for keys on Linux (Will be replaced)
    #  "keyrings.cryptfile==1.3.8",  # Secure storage for keys on Linux (Will be replaced)
    #  See https://github.com/frispete/keyrings.cryptfile/issues/15
    "PyYAML==5.4.1",  # Used for config file format
    "setproctitle==1.2.2",  # Gives the silicoin processes readable names
    "sortedcontainers==2.4.0",  # For maintaining sorted mempools
    "websockets==8.1.0",  # For use in wallet RPC and electron UI
    "click==7.1.2",  # For the CLI
    "dnspythonchia==2.2.0",  # Query DNS seeds
    "packaging==21.0",
    "watchdog==2.1.6",  # Filesystem event watching - watches keyring.yaml
    "nest-asyncio==1.5.1",
]

upnp_dependencies = [
    "miniupnpc==2.2.2",  # Allows users to open ports on their router
]

dev_dependencies = [
    "pytest",
    "pytest-asyncio",
    "flake8",
    "mypy",
    "black",
    "aiohttp_cors",  # For blackd
    "ipython",  # For asyncio debugging
    "types-setuptools",
]

kwargs = dict(
    name="silicoin-blockchain",
    author="Mariano Sorgente",
    author_email="mariano@sitnetwork.net",
    description="Silicoin blockchain full node, farmer, timelord, and wallet.",
    url="https://sitnetwork.net/",
    license="Apache License",
    python_requires=">=3.7, <4",
    keywords="silicoin blockchain node",
    install_requires=dependencies,
    setup_requires=["setuptools_scm"],
    extras_require=dict(
        uvloop=["uvloop"],
        dev=dev_dependencies,
        upnp=upnp_dependencies,
    ),
    packages=[
        "build_scripts",
        "silicoin",
        "silicoin.cmds",
        "silicoin.clvm",
        "silicoin.consensus",
        "silicoin.daemon",
        "silicoin.full_node",
        "silicoin.timelord",
        "silicoin.farmer",
        "silicoin.harvester",
        "silicoin.introducer",
        "silicoin.plotting",
        "silicoin.pools",
        "silicoin.protocols",
        "silicoin.rpc",
        "silicoin.server",
        "silicoin.simulator",
        "silicoin.types.blockchain_format",
        "silicoin.types",
        "silicoin.util",
        "silicoin.wallet",
        "silicoin.wallet.puzzles",
        "silicoin.wallet.rl_wallet",
        "silicoin.wallet.cc_wallet",
        "silicoin.wallet.did_wallet",
        "silicoin.wallet.settings",
        "silicoin.wallet.trading",
        "silicoin.wallet.util",
        "silicoin.ssl",
        "mozilla-ca",
    ],
    entry_points={
        "console_scripts": [
            "silicoin = silicoin.cmds.silicoin:main",
            "silicoin_wallet = silicoin.server.start_wallet:main",
            "silicoin_full_node = silicoin.server.start_full_node:main",
            "silicoin_harvester = silicoin.server.start_harvester:main",
            "silicoin_farmer = silicoin.server.start_farmer:main",
            "silicoin_introducer = silicoin.server.start_introducer:main",
            "silicoin_timelord = silicoin.server.start_timelord:main",
            "silicoin_timelord_launcher = silicoin.timelord.timelord_launcher:main",
            "silicoin_full_node_simulator = silicoin.simulator.start_simulator:main",
        ]
    },
    package_data={
        "silicoin": ["pyinstaller.spec"],
        "": ["*.clvm", "*.clvm.hex", "*.clib", "*.clinc", "*.clsp", "py.typed"],
        "silicoin.util": ["initial-*.yaml", "english.txt"],
        "silicoin.ssl": ["silicoin_ca.crt", "silicoin_ca.key", "dst_root_ca.pem"],
        "mozilla-ca": ["cacert.pem"],
    },
    use_scm_version={"fallback_version": "unknown-no-.git-directory"},
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    zip_safe=False,
)


if __name__ == "__main__":
    setup(**kwargs)
