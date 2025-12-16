# streamlit_app.py
import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from garminconnect import Garmin
import time
import hashlib
import threading
from apscheduler.schedulers.background import BackgroundScheduler
import json
import os

# ==================== CONFIGURATION ====================

# Login credentials (username: password_hash)
LOGIN_CREDENTIALS = {
    "admin": "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918",  # password: "admin"
    "user1": "0b14d501a594442a01c6859541bcb3e8164d183d32937b851835442f69d5c94e",  # password: "password1"
}

# Load Garmin credentials from secrets
@st.cache_resource
def load_config():
    """Load configuration from Streamlit secrets"""
    return {
        "parent1": {
            "name": st.secrets["parent1"]["name"],
            "email": st.secrets["parent1"]["email"],
            "password": st.secrets["parent1"]["password"],
            "avg_hr_threshold": st.secrets["parent1"].get("avg_hr_threshold", 80)
        },
        "parent2": {
            "name": st.secrets["parent2"]["name"],
            "email": st.secrets["parent2"]["email"],
            "password": st.secrets["parent2"]["password"],
            "avg_hr_threshold": st.secrets["parent2"].get("avg_hr_threshold", 80)
        }
    }

CHECK_INTERVAL_HOURS = 1  # Fetch data every hour

# ==================== END CONFIGURATION ====================

st.set_page_config(page_title="Parent Health Monitor", layout="wide", page_icon="❤️")

# Initialize session state
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'health_data' not in st.session_state:
    st.session_state.health_data = {'parent1': {}, 'parent2': {}}
if 'alert_history' not in st.session_state:
    st.session_state.alert_history = []
if 'last_update' not in st.session_state:
    st.session_state.last_update = {}
if 'scheduler_started' not in st.session_state:
    st.session_state.scheduler_started = False

# Hash password function
def hash_password(password):
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

# Login function
def check_login(username, password):
    """Verify login credentials"""
    password_hash = hash_password(password)
    return username in LOGIN_CREDENTIALS and LOGIN_CREDENTIALS[username] == password_hash

# Alert notification function
def log_alert(parent_name, avg_heart_rate, threshold):
    """Log alert for display in dashboard"""
    alert = {
        'parent': parent_name,
        'avg_heart_rate': avg_heart_rate,
        'threshold': threshold,
        'timestamp': datetime.now()
    }
    st.session_state.alert_history.append(alert)
    return True

# Garmin data fetching functions
def fetch_garmin_data(parent_key, config):
    """Fetch all health data from Garmin for a parent"""
    try:
        # Authenticate
        client = Garmin(config['email'], config['password'])
        client.login()
        
        # Fetch 30 days of data
        daily_data = []
        
        for i in range(30):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            
            try:
                # Heart rate data
                hr_data = client.get_heart_rates(date)
                
                # Daily stats
                daily_stats = client.get_stats(date)
                
                # Sleep data
                sleep_data = None
                try:
                    sleep_data = client.get_sleep_data(date)
                except:
                    pass
                
                # Process heart rate
                resting_hr = hr_data.get('restingHeartRate') if hr_data else None
                max_hr = hr_data.get('maxHeartRate') if hr_data else None
                min_hr = hr_data.get('minHeartRate') if hr_data else None
                
                avg_hr = None
                hr_values = []
                if hr_data:
                    hr_values_raw = hr_data.get('heartRateValues', [])
                    if hr_values_raw:
                        valid_hr_values = [hr for t, hr in hr_values_raw if hr is not None]
                        if valid_hr_values:
                            avg_hr = sum(valid_hr_values) / len(valid_hr_values)
                            min_hr = min(valid_hr_values) if not min_hr else min_hr
                        hr_values = hr_values_raw
                
                # Process steps
                steps = daily_stats.get('totalSteps', 0) if daily_stats else 0
                
                # Process SpO2
                spo2_avg = None
                spo2_data = []
                try:
                    spo2_response = client.get_spo2_data(date)
                    if spo2_response:
                        spo2_values = spo2_response.get('values', [])
                        if spo2_values:
                            valid_spo2 = [v['value'] for v in spo2_values if v.get('value')]
                            if valid_spo2:
                                spo2_avg = sum(valid_spo2) / len(valid_spo2)
                            spo2_data = spo2_values
                except:
                    pass
                
                # Process sleep
                sleep_hours = None
                deep_sleep = None
                light_sleep = None
                rem_sleep = None
                awake_time = None
                
                if sleep_data:
                    daily_sleep = sleep_data.get('dailySleepDTO', {})
                    sleep_seconds = daily_sleep.get('sleepTimeSeconds', 0)
                    sleep_hours = sleep_seconds / 3600 if sleep_seconds else None
                    
                    deep_sleep = daily_sleep.get('deepSleepSeconds', 0) / 3600 if daily_sleep.get('deepSleepSeconds') else None
                    light_sleep = daily_sleep.get('lightSleepSeconds', 0) / 3600 if daily_sleep.get('lightSleepSeconds') else None
                    rem_sleep = daily_sleep.get('remSleepSeconds', 0) / 3600 if daily_sleep.get('remSleepSeconds') else None
                    awake_time = daily_sleep.get('awakeSleepSeconds', 0) / 3600 if daily_sleep.get('awakeSleepSeconds') else None
                
                daily_data.append({
                    'date': date,
                    'avg_hr': avg_hr,
                    'resting_hr': resting_hr,
                    'max_hr': max_hr,
                    'min_hr': min_hr,
                    'hr_values': hr_values,
                    'steps': steps,
                    'spo2_avg': spo2_avg,
                    'spo2_data': spo2_data,
                    'sleep_hours': sleep_hours,
                    'deep_sleep': deep_sleep,
                    'light_sleep': light_sleep,
                    'rem_sleep': rem_sleep,
                    'awake_time': awake_time
                })
                
            except Exception as e:
                print(f"Error fetching data for {date}: {str(e)}")
                continue
        
        # Logout
        try:
            client.logout()
        except:
            pass
        
        # Store in session state
        st.session_state.health_data[parent_key] = daily_data
        st.session_state.last_update[parent_key] = datetime.now()
        
        # Check for alerts (today's data)
        if daily_data and daily_data[0].get('avg_hr'):
            avg_hr = daily_data[0]['avg_hr']
            if avg_hr > config['avg_hr_threshold']:
                log_alert(config['name'], avg_hr, config['avg_hr_threshold'])
        
        return True
        
    except Exception as e:
        print(f"Error in fetch_garmin_data for {parent_key}: {str(e)}")
        return False

def scheduled_data_fetch():
    """Background task to fetch data periodically"""
    try:
        PARENT_CONFIGS = load_config()
        for parent_key in ['parent1', 'parent2']:
            config = PARENT_CONFIGS[parent_key]
            fetch_garmin_data(parent_key, config)
    except Exception as e:
        print(f"Error in scheduled fetch: {str(e)}")

# Initialize scheduler
@st.cache_resource
def init_scheduler():
    """Initialize background scheduler"""
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduled_data_fetch, 'interval', hours=CHECK_INTERVAL_HOURS)
    scheduler.start()
    
    # Fetch data immediately on first run
    scheduled_data_fetch()
    
    return scheduler

# Login page
def login_page():
    st.title("🔒 Parent Health Monitor - Login")
    st.markdown("Please log in to access the health monitoring dashboard")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("---")
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        
        if st.button("Login", use_container_width=True):
            if check_login(username, password):
                st.session_state.authenticated = True
                st.success("✅ Login successful!")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("❌ Invalid username or password")
        
        st.markdown("---")
        st.caption("Contact administrator for access credentials")

# Plot heart rate for a day
def plot_heart_rate_day(hr_values, date, threshold):
    """Create detailed heart rate plot for a single day"""
    if not hr_values:
        return None
    
    times = []
    hrs = []
    
    for timestamp, hr in hr_values:
        if hr is not None:
            times.append(datetime.fromtimestamp(timestamp / 1000))
            hrs.append(hr)
    
    if not times:
        return None
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=times,
        y=hrs,
        mode='lines',
        name='Heart Rate',
        line=dict(color='#3b82f6', width=2),
        fill='tozeroy',
        fillcolor='rgba(59, 130, 246, 0.1)'
    ))
    
    fig.add_hline(
        y=threshold,
        line_dash="dash",
        line_color="orange",
        annotation_text=f"Threshold ({threshold} bpm)"
    )
    
    fig.update_layout(
        title=f"Heart Rate Throughout Day - {date}",
        xaxis_title="Time",
        yaxis_title="Heart Rate (bpm)",
        height=350,
        hovermode='x unified',
        margin=dict(l=20, r=20, t=40, b=20)
    )
    
    return fig

# Main dashboard
def main_dashboard():
    # Initialize scheduler
    if not st.session_state.scheduler_started:
        init_scheduler()
        st.session_state.scheduler_started = True
    
    PARENT_CONFIGS = load_config()
    
    st.title("❤️ Parents Health Monitor")
    st.markdown("Real-time health tracking from Garmin devices")
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Settings")
        
        st.markdown(f"""
        **Monitoring:**
        - Parent 1: {PARENT_CONFIGS['parent1']['name']}
        - Parent 2: {PARENT_CONFIGS['parent2']['name']}
        
        **Alert Threshold:**
        - Avg Daily HR > {PARENT_CONFIGS['parent1']['avg_hr_threshold']} bpm
        
        **Data Refresh:**
        - Every {CHECK_INTERVAL_HOURS} hour(s)
        """)
        
        st.markdown("---")
        
        # Show last update times
        st.subheader("Last Updated")
        for parent_key in ['parent1', 'parent2']:
            if parent_key in st.session_state.last_update:
                last_update = st.session_state.last_update[parent_key]
                st.caption(f"{PARENT_CONFIGS[parent_key]['name']}: {last_update.strftime('%Y-%m-%d %H:%M:%S')}")
        
        st.markdown("---")
        
        if st.button("🔄 Refresh Now", use_container_width=True):
            with st.spinner("Fetching latest data..."):
                scheduled_data_fetch()
            st.success("Data refreshed!")
            st.rerun()
        
        st.markdown("---")
        
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()
    
    # Main content
    if not st.session_state.health_data.get('parent1') and not st.session_state.health_data.get('parent2'):
        st.info("⏳ Loading health data... This may take a moment on first load.")
        return
    
    # Create tabs for each parent and alerts
    parent1_name = PARENT_CONFIGS['parent1']['name']
    parent2_name = PARENT_CONFIGS['parent2']['name']
    
    tabs = st.tabs([parent1_name, parent2_name, "🚨 Alerts"])
    
    # Display data for each parent
    for idx, (tab, parent_key) in enumerate([
        (tabs[0], 'parent1'),
        (tabs[1], 'parent2')
    ]):
        with tab:
            config = PARENT_CONFIGS[parent_key]
            data = st.session_state.health_data.get(parent_key, [])
            
            if not data:
                st.warning(f"No data available for {config['name']}")
                continue
            
            # Today's metrics
            today_data = data[0] if data else {}
            
            st.subheader("📊 Today's Metrics")
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                avg_hr = today_data.get('avg_hr')
                if avg_hr:
                    delta = "⚠️ ALERT" if avg_hr > config['avg_hr_threshold'] else None
                    st.metric("Avg Heart Rate", f"{avg_hr:.1f} bpm", delta=delta)
                else:
                    st.metric("Avg Heart Rate", "N/A")
            
            with col2:
                resting_hr = today_data.get('resting_hr')
                st.metric("Resting HR", f"{resting_hr} bpm" if resting_hr else "N/A")
            
            with col3:
                max_hr = today_data.get('max_hr')
                st.metric("Max HR", f"{max_hr} bpm" if max_hr else "N/A")
            
            with col4:
                steps = today_data.get('steps')
                st.metric("Steps", f"{steps:,}" if steps else "N/A")
            
            with col5:
                spo2 = today_data.get('spo2_avg')
                st.metric("SpO2 Avg", f"{spo2:.1f}%" if spo2 else "N/A")
            
            # Create DataFrame for plotting
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            
            st.markdown("---")
            
            # TWO COLUMN LAYOUT FOR CHARTS
            
            # ROW 1: Heart Rate Trends & Today's Detail
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("📈 30-Day Heart Rate Trends")
                
                fig_hr = go.Figure()
                
                fig_hr.add_trace(go.Scatter(
                    x=df['date'], y=df['avg_hr'],
                    mode='lines+markers', name='Average HR',
                    line=dict(color='#3b82f6', width=3), marker=dict(size=6)
                ))
                
                fig_hr.add_trace(go.Scatter(
                    x=df['date'], y=df['max_hr'],
                    mode='lines+markers', name='Max HR',
                    line=dict(color='#ef4444', width=2), marker=dict(size=5)
                ))
                
                fig_hr.add_trace(go.Scatter(
                    x=df['date'], y=df['min_hr'],
                    mode='lines+markers', name='Min HR',
                    line=dict(color='#10b981', width=2), marker=dict(size=5)
                ))
                
                fig_hr.add_trace(go.Scatter(
                    x=df['date'], y=df['resting_hr'],
                    mode='lines+markers', name='Resting HR',
                    line=dict(color='#8b5cf6', width=2, dash='dot'), marker=dict(size=5)
                ))
                
                fig_hr.add_hline(
                    y=config['avg_hr_threshold'],
                    line_dash="dash", line_color="orange",
                    annotation_text=f"Alert Threshold"
                )
                
                fig_hr.update_layout(
                    xaxis_title="Date", yaxis_title="Heart Rate (bpm)",
                    height=350, hovermode='x unified',
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    margin=dict(l=20, r=20, t=20, b=20)
                )
                
                st.plotly_chart(fig_hr, use_container_width=True, key=f"{parent_key}_hr_trends")
            
            with col2:
                st.subheader("🔍 Today's Heart Rate Detail")
                if today_data.get('hr_values'):
                    fig_today = plot_heart_rate_day(
                        today_data['hr_values'],
                        today_data['date'],
                        config['avg_hr_threshold']
                    )
                    if fig_today:
                        st.plotly_chart(fig_today, use_container_width=True, key=f"{parent_key}_hr_today")
                else:
                    st.info("No detailed heart rate data available for today")
            
            # ROW 2: Steps & Heart Rate Variability
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("👣 30-Day Daily Steps")
                
                fig_steps = go.Figure()
                
                fig_steps.add_trace(go.Bar(
                    x=df['date'], y=df['steps'],
                    name='Daily Steps',
                    marker_color='#10b981'
                ))
                
                fig_steps.add_hline(
                    y=10000,
                    line_dash="dash", line_color="gray",
                    annotation_text="10K goal"
                )
                
                fig_steps.update_layout(
                    xaxis_title="Date", yaxis_title="Steps",
                    height=350, hovermode='x',
                    margin=dict(l=20, r=20, t=20, b=20)
                )
                
                st.plotly_chart(fig_steps, use_container_width=True, key=f"{parent_key}_steps")
            
            with col2:
                st.subheader("💓 Heart Rate Range Distribution")
                
                # Calculate HR range (max - min) for each day
                df['hr_range'] = df['max_hr'] - df['min_hr']
                
                fig_range = go.Figure()
                
                fig_range.add_trace(go.Scatter(
                    x=df['date'], y=df['hr_range'],
                    mode='lines+markers',
                    name='HR Range',
                    line=dict(color='#f59e0b', width=2),
                    marker=dict(size=7),
                    fill='tozeroy',
                    fillcolor='rgba(245, 158, 11, 0.1)'
                ))
                
                fig_range.update_layout(
                    xaxis_title="Date", yaxis_title="Range (bpm)",
                    height=350, hovermode='x',
                    margin=dict(l=20, r=20, t=20, b=20)
                )
                
                st.plotly_chart(fig_range, use_container_width=True, key=f"{parent_key}_hr_range")
            
            # ROW 3: Sleep Analysis & SpO2
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("😴 30-Day Sleep Composition")
                
                fig_sleep = go.Figure()
                
                fig_sleep.add_trace(go.Bar(
                    x=df['date'], y=df['deep_sleep'],
                    name='Deep Sleep',
                    marker_color='#6366f1'
                ))
                
                fig_sleep.add_trace(go.Bar(
                    x=df['date'], y=df['light_sleep'],
                    name='Light Sleep',
                    marker_color='#8b5cf6'
                ))
                
                fig_sleep.add_trace(go.Bar(
                    x=df['date'], y=df['rem_sleep'],
                    name='REM Sleep',
                    marker_color='#a855f7'
                ))
                
                fig_sleep.add_trace(go.Bar(
                    x=df['date'], y=df['awake_time'],
                    name='Awake',
                    marker_color='#ef4444'
                ))
                
                fig_sleep.update_layout(
                    barmode='stack',
                    xaxis_title="Date", yaxis_title="Hours",
                    height=350, hovermode='x unified',
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    margin=dict(l=20, r=20, t=20, b=20)
                )
                
                st.plotly_chart(fig_sleep, use_container_width=True, key=f"{parent_key}_sleep")
            
            with col2:
                st.subheader("🫁 30-Day Pulse Oxygen (SpO2)")
                
                fig_spo2 = go.Figure()
                
                fig_spo2.add_trace(go.Scatter(
                    x=df['date'], y=df['spo2_avg'],
                    mode='lines+markers',
                    name='Average SpO2',
                    line=dict(color='#06b6d4', width=3),
                    marker=dict(size=7),
                    fill='tonexty',
                    fillcolor='rgba(6, 182, 212, 0.1)'
                ))
                
                fig_spo2.add_hrect(
                    y0=95, y1=100,
                    fillcolor="green", opacity=0.1,
                    annotation_text="Normal Range", annotation_position="top left"
                )
                
                fig_spo2.update_layout(
                    xaxis_title="Date", yaxis_title="SpO2 (%)",
                    height=350, hovermode='x unified',
                    yaxis=dict(range=[90, 100]),
                    margin=dict(l=20, r=20, t=20, b=20)
                )
                
                st.plotly_chart(fig_spo2, use_container_width=True, key=f"{parent_key}_spo2")
            
            # ROW 4: Total Sleep Hours & Resting HR Trend
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("🌙 Total Sleep Duration Trend")
                
                fig_total_sleep = go.Figure()
                
                fig_total_sleep.add_trace(go.Scatter(
                    x=df['date'], y=df['sleep_hours'],
                    mode='lines+markers',
                    name='Total Sleep',
                    line=dict(color='#8b5cf6', width=3),
                    marker=dict(size=7),
                    fill='tozeroy',
                    fillcolor='rgba(139, 92, 246, 0.1)'
                ))
                
                # Add recommended sleep line
                fig_total_sleep.add_hline(
                    y=7,
                    line_dash="dash", line_color="green",
                    annotation_text="Recommended (7-9 hrs)"
                )
                
                fig_total_sleep.update_layout(
                    xaxis_title="Date", yaxis_title="Hours",
                    height=350, hovermode='x',
                    margin=dict(l=20, r=20, t=20, b=20)
                )
                
                st.plotly_chart(fig_total_sleep, use_container_width=True, key=f"{parent_key}_total_sleep")
            
            with col2:
                st.subheader("🧘 Resting Heart Rate Trend")
                
                fig_resting = go.Figure()
                
                # Add moving average
                df['resting_hr_ma'] = df['resting_hr'].rolling(window=7, min_periods=1).mean()
                
                fig_resting.add_trace(go.Scatter(
                    x=df['date'], y=df['resting_hr'],
                    mode='markers',
                    name='Daily Resting HR',
                    marker=dict(color='#3b82f6', size=6),
                    opacity=0.5
                ))
                
                fig_resting.add_trace(go.Scatter(
                    x=df['date'], y=df['resting_hr_ma'],
                    mode='lines',
                    name='7-Day Average',
                    line=dict(color='#ef4444', width=3)
                ))
                
                fig_resting.update_layout(
                    xaxis_title="Date", yaxis_title="Heart Rate (bpm)",
                    height=350, hovermode='x unified',
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    margin=dict(l=20, r=20, t=20, b=20)
                )
                
                st.plotly_chart(fig_resting, use_container_width=True, key=f"{parent_key}_resting_hr")
            
            # Summary Statistics
            st.markdown("---")
            st.subheader("📋 30-Day Summary Statistics")
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                avg_hr_30 = df['avg_hr'].mean()
                st.metric("Avg Heart Rate", f"{avg_hr_30:.1f} bpm")
            
            with col2:
                avg_steps_30 = df['steps'].mean()
                st.metric("Avg Daily Steps", f"{avg_steps_30:,.0f}")
            
            with col3:
                avg_sleep_30 = df['sleep_hours'].mean()
                st.metric("Avg Sleep", f"{avg_sleep_30:.1f} hrs" if not pd.isna(avg_sleep_30) else "N/A")
            
            with col4:
                avg_spo2_30 = df['spo2_avg'].mean()
                st.metric("Avg SpO2", f"{avg_spo2_30:.1f}%" if not pd.isna(avg_spo2_30) else "N/A")
            
            with col5:
                avg_resting_30 = df['resting_hr'].mean()
                st.metric("Avg Resting HR", f"{avg_resting_30:.1f} bpm" if not pd.isna(avg_resting_30) else "N/A")
    
    # Alerts tab
    with tabs[2]:
        st.subheader("🚨 Recent Alerts")
        st.markdown("*Alerts are triggered when average daily heart rate exceeds threshold*")
        
        if st.session_state.alert_history:
            for alert in reversed(st.session_state.alert_history[-20:]):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.error(f"""
                    **{alert['parent']}** - Average HR: **{alert['avg_heart_rate']:.1f} bpm** 
                    (Threshold: {alert['threshold']} bpm)
                    """)
                with col2:
                    st.caption(alert['timestamp'].strftime('%Y-%m-%d %H:%M:%S'))
            
            if st.button("Clear Alert History"):
                st.session_state.alert_history = []
                st.rerun()
        else:
            st.success("No alerts recorded ✅")

# Main application
def main():
    if not st.session_state.authenticated:
        login_page()
    else:
        main_dashboard()

if __name__ == "__main__":
    main()