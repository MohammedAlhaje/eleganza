#!/usr/bin/env python3
"""
Django File Combiner - Combines selectors/services files across all apps
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Optional

# ===================== GLOBAL CONFIGURATION =====================
# These are the default values that can be overridden by command line args
_FORCE_OVERWRITE: bool = False
_DRY_RUN: bool = False
_VERBOSE: bool = True

# Other configuration constants
_TARGET_FOLDERS: List[str] = ['selectors', 'services']
_EXCLUDE_FILES: List[str] = ['__init__.py']
_OUTPUT_PATTERN: str = "{parent}_{folder}_combined.py"
# ================================================================

class DjangoFileCombiner:
    def __init__(self):
        self.project_root: Optional[Path] = None
        self.apps_root: Optional[Path] = None

    def find_django_root(self) -> Path:
        """Locate Django project root by finding manage.py"""
        path = Path(__file__).absolute().parent
        while path != path.parent:
            if (path / "manage.py").exists():
                if _VERBOSE:
                    print(f"🔍 Found Django project at: {path}")
                return path
            path = path.parent
        raise FileNotFoundError("Could not find Django project root (no manage.py)")

    def find_apps_directory(self) -> Path:
        """Determine where apps are stored"""
        possible_locations = [
            self.project_root / "apps",
            self.project_root / self.project_root.name,
            self.project_root
        ]
        for location in possible_locations:
            if location.exists():
                if _VERBOSE:
                    print(f"📦 Found apps directory at: {location.relative_to(self.project_root)}")
                return location
        return self.project_root

    def discover_targets(self) -> List[Dict]:
        """Find all target directories with Python files"""
        targets = []
        for target in _TARGET_FOLDERS:
            for dirpath in self.apps_root.rglob(target):
                if dirpath.is_dir():
                    py_files = [
                        f for f in dirpath.glob('*.py') 
                        if f.name not in _EXCLUDE_FILES
                    ]
                    if py_files:
                        targets.append({
                            'path': dirpath,
                            'files': sorted(py_files),
                            'parent': dirpath.parent.name,
                            'folder': dirpath.name
                        })
                        if _VERBOSE:
                            print(f"✅ Found {len(py_files)} files in {dirpath.relative_to(self.project_root)}")
        return targets

    def should_process(self, output_path: Path) -> bool:
        """Check if we should process this directory"""
        if not _FORCE_OVERWRITE and output_path.exists():
            print(f"⏩ Skipping (exists): {output_path.relative_to(self.project_root)}")
            return False
        if _DRY_RUN:
            print(f"🏃‍♂️ DRY RUN: Would process {output_path.parent.relative_to(self.project_root)}")
            return False
        return True

    def combine_files(self, target: Dict) -> bool:
        """Combine files into single output"""
        output_path = target['path'] / _OUTPUT_PATTERN.format(
            parent=target['parent'],
            folder=target['folder']
        )
        
        if not self.should_process(output_path):
            return False

        try:
            with open(output_path, 'w', encoding='utf-8') as outfile:
                for file in target['files']:
                    rel_path = file.relative_to(self.project_root)
                    header = f"\n#{'='*40}\n# {rel_path}\n#{'='*40}\n\n"
                    outfile.write(header)
                    with open(file, 'r') as infile:
                        outfile.write(infile.read() + '\n')
            
            print(f"📄 Created {output_path.relative_to(self.project_root)}")
            return True
        except Exception as e:
            print(f"❌ Failed to write {output_path}: {e}", file=sys.stderr)
            return False

    def run(self) -> bool:
        """Main execution flow"""
        try:
            # Initialize project
            self.project_root = self.find_django_root()
            self.apps_root = self.find_apps_directory()
            
            if _VERBOSE:
                print(f"\n🔎 Searching for: {_TARGET_FOLDERS}")
                print(f"🚫 Excluding: {_EXCLUDE_FILES}")
                if _DRY_RUN:
                    print("🌵 DRY RUN MODE - No changes will be made")
                elif _FORCE_OVERWRITE:
                    print("💥 FORCE OVERWRITE ENABLED")

            # Find and process targets
            targets = self.discover_targets()
            if not targets:
                print("\n⚠️ No target directories found with matching files")
                print(f"Scanned: {self.apps_root.relative_to(self.project_root)}")
                return False

            print("\n🚀 Processing directories...")
            results = [self.combine_files(t) for t in targets]
            
            # Summary
            success_count = sum(results)
            print(f"\n✅ Successfully processed {success_count}/{len(results)} directories")
            if _DRY_RUN:
                print("💡 Tip: Run without --dry-run to execute changes")
            return success_count == len(results)

        except Exception as e:
            print(f"\n❌ Fatal error: {e}", file=sys.stderr)
            return False

def main():
    # Declare we're using the global config variables
    global _FORCE_OVERWRITE, _DRY_RUN, _VERBOSE
    
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")
    args = parser.parse_args()

    # Apply CLI overrides
    _FORCE_OVERWRITE = args.force
    _DRY_RUN = args.dry_run
    _VERBOSE = not args.quiet

    combiner = DjangoFileCombiner()
    sys.exit(0 if combiner.run() else 1)

if __name__ == "__main__":
    main()