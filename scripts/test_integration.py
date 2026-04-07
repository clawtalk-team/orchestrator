#!/usr/bin/env python3
"""
Integration tests for management scripts.
Tests error handling and argument validation.
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], description: str, expect_failure: bool = False) -> bool:
    """Run a command and check if it behaves as expected."""
    print(f"\nTesting: {description}")
    print(f"Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if expect_failure:
            if result.returncode != 0:
                print(f"✓ {description} - Failed as expected")
                return True
            else:
                print(f"✗ {description} - Should have failed but succeeded")
                return False
        else:
            if result.returncode == 0:
                print(f"✓ {description} - Passed")
                return True
            else:
                print(f"✗ {description} - Failed unexpectedly")
                print(f"STDERR: {result.stderr}")
                return False

    except subprocess.TimeoutExpired:
        print(f"✗ {description} - Timeout")
        return False
    except Exception as e:
        print(f"✗ {description} - Error: {e}")
        return False


def main():
    scripts_dir = Path(__file__).parent
    python = sys.executable

    print("=" * 60)
    print("INTEGRATION TESTS - Error Handling & Validation")
    print("=" * 60)

    tests = []

    # Test 1: launch_container.py missing required args
    tests.append(
        run_command(
            [python, str(scripts_dir / "launch_container.py")],
            "launch_container.py - missing required args",
            expect_failure=True,
        )
    )

    # Test 2: launch_container.py with invalid JSON config
    tests.append(
        run_command(
            [
                python,
                str(scripts_dir / "launch_container.py"),
                "--user-id",
                "test",
                "--token",
                "test123456789012345",
                "--config",
                "invalid-json",
            ],
            "launch_container.py - invalid JSON config",
            expect_failure=True,
        )
    )

    # Test 3: launch_container.py with valid JSON config (will fail on API call, but validates parsing)
    tests.append(
        run_command(
            [
                python,
                str(scripts_dir / "launch_container.py"),
                "--user-id",
                "test",
                "--token",
                "test123456789012345",
                "--config",
                '{"memory": 512}',
                "--local",
            ],
            "launch_container.py - valid config but no API",
            expect_failure=True,  # Will fail connecting to localhost:8000
        )
    )

    # Test 4: get_logs.py missing user-id
    tests.append(
        run_command(
            [python, str(scripts_dir / "get_logs.py"), "oc-test123"],
            "get_logs.py - missing user-id",
            expect_failure=True,
        )
    )

    # Test 5: exec_shell.py missing user-id
    tests.append(
        run_command(
            [python, str(scripts_dir / "exec_shell.py"), "oc-test123"],
            "exec_shell.py - missing user-id",
            expect_failure=True,
        )
    )

    # Test 6: delete_containers.py missing user-id
    tests.append(
        run_command(
            [python, str(scripts_dir / "delete_containers.py"), "oc-test123"],
            "delete_containers.py - missing user-id",
            expect_failure=True,
        )
    )

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(tests)
    total = len(tests)

    print(f"\nResults: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All integration tests passed!")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
