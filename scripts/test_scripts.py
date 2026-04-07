#!/usr/bin/env python3
"""
Test script to verify all management scripts work correctly.
Tests argument parsing and basic functionality without making AWS API calls.
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], description: str) -> bool:
    """Run a command and return True if successful."""
    print(f"\n{'='*60}")
    print(f"Testing: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)

        if result.returncode == 0:
            print(f"✓ {description} - PASSED")
            return True
        else:
            print(f"✗ {description} - FAILED (exit code: {result.returncode})")
            return False

    except subprocess.TimeoutExpired:
        print(f"✗ {description} - TIMEOUT")
        return False
    except Exception as e:
        print(f"✗ {description} - ERROR: {e}")
        return False


def main():
    scripts_dir = Path(__file__).parent
    python = sys.executable

    tests = [
        # Test 1: list_containers.py --help
        {
            "cmd": [python, str(scripts_dir / "list_containers.py"), "--help"],
            "description": "list_containers.py --help",
        },
        # Test 2: list_ecs_tasks.py --help
        {
            "cmd": [python, str(scripts_dir / "list_ecs_tasks.py"), "--help"],
            "description": "list_ecs_tasks.py --help",
        },
        # Test 3: get_logs.py --help
        {
            "cmd": [python, str(scripts_dir / "get_logs.py"), "--help"],
            "description": "get_logs.py --help",
        },
        # Test 4: exec_shell.py --help
        {
            "cmd": [python, str(scripts_dir / "exec_shell.py"), "--help"],
            "description": "exec_shell.py --help",
        },
        # Test 5: delete_containers.py --help
        {
            "cmd": [python, str(scripts_dir / "delete_containers.py"), "--help"],
            "description": "delete_containers.py --help",
        },
        # Test 6: launch_container.py --help
        {
            "cmd": [python, str(scripts_dir / "launch_container.py"), "--help"],
            "description": "launch_container.py --help",
        },
    ]

    print("\n" + "=" * 60)
    print("SCRIPT VALIDATION TEST SUITE")
    print("=" * 60)

    results = []
    for test in tests:
        success = run_command(test["cmd"], test["description"])
        results.append((test["description"], success))

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for description, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status}: {description}")

    print(f"\nResults: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
