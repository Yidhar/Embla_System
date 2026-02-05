import antfu from '@antfu/eslint-config'

export default antfu({
  ignores: ['**/node_modules/**', '**/dist/**', '**/public/**'],
  rules: {
    'vue/singleline-html-element-content-newline': ['warn', {
      ignores: ['template'],
    }],
  },
})
