from setuptools import setup, find_packages

setup(
    name="marlinsim-gcode",
    version="0.1.0",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "marlinsim-gcode=marlinsim.cli:main",
        ],
    },
    python_requires=">=3.8",
)
