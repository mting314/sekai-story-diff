// Conventional Commits (https://www.conventionalcommits.org) for local commit messages,
// enforced by the husky `commit-msg` hook (.husky/commit-msg). Type list kept in sync
// with the other repos in this workspace.
export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [2, 'always', ['feat', 'fix', 'chore', 'docs', 'refactor', 'test', 'perf', 'build', 'ci']],
    // commit bodies here carry a lot of reasoning; do not wrap-police them
    'body-max-line-length': [0],
    'footer-max-line-length': [0],
  }
};
