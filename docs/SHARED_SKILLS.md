# Shared Skills

## Purpose

Shared Skills are reusable, installable instruction bundles. One library is used by Kira, Ren, Mika and custom characters; a Skill is not copied into a character profile and does not depend on the active persona.

## Package format

A Skill directory or ZIP contains:

- \`manifest.json\`
- \`SKILL.md\`

Example manifest:

\`\`\`json
{
  "id": "research-helper",
  "name": "Research Helper",
  "version": "1.0.0",
  "description": "A structured research workflow"
}
\`\`\`

Skill IDs are lowercase and unique. Only \`SKILL.md\` is loaded. Python modules, executables, shell scripts and other bundled code are never imported or executed.

## Runtime and storage

The desktop app creates one \`SharedSkillService\` at \`DATA_DIR/skills\`. Its public API is:

- \`install(path)\`: install a directory or ZIP atomically.
- \`list_installed()\`: list validated packages.
- \`set_enabled(settings, skill_id, True/False)\`: enable/disable globally.
- \`set_enabled(settings, skill_id, True/False, character_id="ren")\`: add or disable for one character.
- \`enabled_for(settings, character_id)\`: resolve the effective Skill set.
- \`prompt_for(settings, character_id)\`: build the bounded prompt contribution.
- \`uninstall(skill_id, settings)\`: remove the package and clean enablement references.

The app resolves the active character's enabled Skills for every chat turn. Global Skills apply to all characters unless that character has an explicit disable override. Character-only Skills do not leak into other characters. The \`shared_skills\` settings object is persisted by the existing application settings mechanism.

## Safety boundaries

- ZIP traversal, absolute paths, Windows drive/backslash paths, symlinks, excessive file counts and oversized packages are rejected.
- The library has a 200-Skill limit; each package is limited to 64 files, 256 KiB per file and 1 MiB total.
- Prompt contribution is capped at 20,000 characters.
- Skill content is marked as untrusted guidance and cannot override system/developer policy, user intent, safety checks or tool permission checks.
- A Skill does not receive a tool, shell, filesystem or network capability merely by being installed.
- Installing a Skill does not automatically enable it globally or for any character.

## Current delivery boundary

The registry, installer, global/per-character enablement policy and chat prompt integration are implemented. The desktop runtime exposes \`window.skill_service\` for the management UI or trusted application workflows. A dedicated Skills management page/dialog is not part of this change; until that UI is added, installation and enablement are available through the service API and settings object. Runtime tests and Windows desktop acceptance must still be executed before release.
