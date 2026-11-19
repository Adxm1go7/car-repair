import type { JSX } from 'react'
import { NavLink, useParams } from 'react-router'
import { BaysTab } from './BaysTab.tsx'
import { ContactTab } from './ContactTab.tsx'
import { HoursTab } from './HoursTab.tsx'
import { ServicesTab } from './ServicesTab.tsx'

const TABS = [
  { path: 'services', label: 'Services' },
  { path: 'bays', label: 'Bays' },
  { path: 'hours', label: 'Hours' },
  { path: 'contact', label: 'Contact' },
] as const

type Tab = (typeof TABS)[number]['path']

function isTab(value: string | undefined): value is Tab {
  return TABS.some((tab) => tab.path === value)
}

function TabContent({ tab }: { tab: Tab }): JSX.Element {
  switch (tab) {
    case 'services':
      return <ServicesTab />
    case 'bays':
      return <BaysTab />
    case 'hours':
      return <HoursTab />
    case 'contact':
      return <ContactTab />
  }
}

/** `/staff/settings/:tab` (admin only): the garage's services, bays, hours and contact
 * details. The URL keeps the tab. */
export function SettingsPage(): JSX.Element {
  const { tab } = useParams()
  return (
    <div className="settings-page">
      <h1>Settings</h1>
      <nav className="settings-tabs" aria-label="Settings">
        {TABS.map(({ path, label }) => (
          <NavLink key={path} to={`/staff/settings/${path}`}>
            {label}
          </NavLink>
        ))}
      </nav>
      {isTab(tab) ? <TabContent tab={tab} /> : <p>Page not found</p>}
    </div>
  )
}
