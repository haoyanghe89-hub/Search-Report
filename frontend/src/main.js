import { createApp } from 'vue'
import App from './App.vue'
import { useTheme } from './composables/useTheme'

import './styles/tokens.css'
import './styles/base.css'
import './styles/folio-ui.css'

useTheme()

createApp(App).mount('#app')
