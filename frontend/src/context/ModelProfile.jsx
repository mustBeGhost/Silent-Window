import { createContext, useContext, useEffect, useState } from 'react'

import { getModelOptions } from '../services/api'
import { useAuth } from './Auth'

export const ModelProfileContext = createContext({
  modelProfile: 'original', setModelProfile: () => {}, options: [], optionsState: 'loading',
})

export function ModelProfileProvider({ children }) {
  const { user } = useAuth()
  const [modelProfile, setModelProfile] = useState('original')
  const [options, setOptions] = useState([])
  const [optionsState, setOptionsState] = useState('loading')
  useEffect(() => {
    const controller = new AbortController()
    getModelOptions({ signal: controller.signal })
      .then((data) => { setOptions(data); setOptionsState('ready') })
      .catch((error) => { if (error.name !== 'AbortError') setOptionsState('error') })
    return () => controller.abort()
  }, [])
  useEffect(() => {
    if (!options.length) return
    const preferred = user?.preferences?.preferred_model || 'original'
    setModelProfile(options.some((option) => option.id === preferred && option.available) ? preferred : 'original')
  }, [options, user?.preferences?.preferred_model])
  function chooseModel(nextProfile) {
    if (options.some((option) => option.id === nextProfile && option.available)) {
      setModelProfile(nextProfile)
    }
  }
  return (
    <ModelProfileContext.Provider value={{ modelProfile, setModelProfile: chooseModel, options, optionsState }}>
      {children}
    </ModelProfileContext.Provider>
  )
}

export function useModelProfile() {
  return useContext(ModelProfileContext)
}
