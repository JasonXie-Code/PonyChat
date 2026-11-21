// 地理位置屏蔽配置
const BLOCKED_REGIONS = {
    // 始终屏蔽的州/省
    permanent: [
        'Alabama', 'Arkansas', 'Florida', 'Georgia', 'Idaho', 'Indiana', 
        'Kansas', 'Kentucky', 'Louisiana', 'Mississippi', 'Montana', 
        'Nebraska', 'North Carolina', 'Oklahoma', 'South Carolina', 
        'South Dakota', 'Tennessee', 'Texas', 'Utah', 'Virginia', 'Wyoming',
    ],
    // 按时间段屏蔽的州/省
    scheduled: {
        'Arizona': new Date('2025-09-26'),
        'Ohio': new Date('2025-09-29'),
        'Missouri': new Date('2025-08-30'),
        'North Dakota': new Date('2025-08-01')
    },
    // 始终屏蔽的国家
    countries: ['United Kingdom', 'UK', 'GB']
};

let userLocationChecked = false;
let downloadsBlocked = false;

function checkLocationRestrictions(location) {
    const currentDate = new Date();
    
    // 检查国家是否被屏蔽
    if (location.country && BLOCKED_REGIONS.countries.some(country => 
        location.country.toLowerCase().includes(country.toLowerCase()) ||
        location.countryCode === 'GB' || location.countryCode === 'UK')) {
        return true;
    }
    
    // 检查州/省是否永久屏蔽
    if (location.region && BLOCKED_REGIONS.permanent.some(state => 
        location.region.toLowerCase().includes(state.toLowerCase()))) {
        return true;
    }
    
    // 按日期检查州/省是否屏蔽
    if (location.region) {
        for (const [state, blockDate] of Object.entries(BLOCKED_REGIONS.scheduled)) {
            if (location.region.toLowerCase().includes(state.toLowerCase()) && 
                currentDate >= blockDate) {
                return true;
            }
        }
    }
    
    return false;
}

function blockDownloads() {
    downloadsBlocked = true;
    const downloadsSection = document.getElementById('downloads');
    const playButton = document.querySelector('.button-play');
    
    if (downloadsSection) {
        // 隐藏下载区域
        downloadsSection.style.display = 'none';
        
        // 创建并插入屏蔽提示
        const blockedMessage = document.createElement('div');
        blockedMessage.id = 'downloads-blocked';
        blockedMessage.className = 'downloads';
        blockedMessage.innerHTML = `
            <h1>Downloads</h1>
            <div style="text-align: center; padding: 30px; background-color: #FD92BF; border: solid #AB0249 2.5pt; border-radius: 8px; margin: 20px 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">
                <h3 style="color: #d32f2f; margin-bottom: 15px;">⚠️ Downloads Unavailable</h3>
                <p style="color: black; font-size: 16px; margin-bottom: 15px; font-weight: 600;">
                    We are legally required to block downloads in your region.
                </p>
                <div style="text-align: left; max-width: 600px; margin: 0 auto;">
                    <p style="color: black; font-size: 14px; margin-bottom: 12px;">
                        <span style="font-weight: 600;">We do NOT want to do this</span>, but we must comply with local regulations or face egregious fines and possibly criminal charges:
                    </p>
                    <ul style="color: black; font-size: 14px; margin-bottom: 15px; text-align: left;">
                        <li><span style="font-weight: 600;">US States:</span> New age verification laws require invasive identity checks that compromise user privacy</li>
                        <li><span style="font-weight: 600;">United Kingdom:</span> OFCOM regulations under the Online Safety Act restrict access to adult content</li>
                    </ul>
                    <p style="color: black; font-size: 14px; margin-bottom: 15px;">
                        <span style="font-weight: 600;">Take Action:</span>
                    </p>
                    <div style="margin-bottom: 15px;">
                        <a href="https://stopcensoring.games/" target="_blank" style="display: inline-block; background-color: #1976d2; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px; margin: 4px; font-size: 14px;">
                            🇺🇸 Fight US Censorship
                        </a>
                        <a href="https://petition.parliament.uk/petitions/722903" target="_blank" style="display: inline-block; background-color: #d32f2f; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px; margin: 4px; font-size: 14px;">
                            🇬🇧 UK Parliamentary Petition
                        </a>
                    </div>
                </div>
                <p style="color: black; font-size: 14px; margin-top: 20px;">
                    You may still be able to access our games by pledging on our <a href="https://www.patreon.com/StudioWhy" class="patreon-link" style="color: #1976d2; font-weight: 600;">Patreon page</a>.
                </p>
                <div style="margin-top: 20px; padding: 15px; background-color: rgba(255,255,255,0.3); border-radius: 6px;">
                    <p style="color: black; font-size: 14px; margin: 0; font-weight: 600;">
                        But we have a plan to help ALL creators resist censorship, follow us on <a href="https://x.com/StudioWhyNot" target="_blank" style="color: #1976d2; text-decoration: underline;">Twitter/X</a> to learn more!
                    </p>
                </div>
            </div>
        `;
        
        // 在下载区域后插入屏蔽提示
        downloadsSection.parentNode.insertBefore(blockedMessage, downloadsSection.nextSibling);
    }
    
    // 将播放按钮改为滚动至屏蔽提示
    if (playButton) {
        playButton.onclick = function(e) {
            e.preventDefault();
            const blockedSection = document.getElementById('downloads-blocked');
            if (blockedSection) {
                blockedSection.scrollIntoView({ behavior: 'smooth' });
            }
            return false;
        };
    }
}

function getUserLocation() {
    // 尝试多个地理定位服务以提高精度
    const services = [
        'https://ipapi.co/json/',
        'https://ipinfo.io/json',
        'https://api.ipgeolocation.io/ipgeo?apiKey=free'
    ];
    
    async function tryService(serviceUrl) {
        try {
            const response = await fetch(serviceUrl);
            const data = await response.json();
            
            // 统一响应格式
            let location = {};
            if (data.region_name || data.region) {
                location.region = data.region_name || data.region;
            }
            if (data.country_name || data.country) {
                location.country = data.country_name || data.country;
            }
            if (data.country_code) {
                location.countryCode = data.country_code;
            }
            
            return location;
        } catch (error) {
            console.warn('Geolocation service failed:', serviceUrl, error);
            return null;
        }
    }
    
    // 依次尝试各服务
    services.reduce((promise, service) => {
        return promise.catch(() => tryService(service));
    }, tryService(services[0]))
    .then(location => {
        if (location && (location.region || location.country)) {
            console.log('User location detected:', location);
            if (checkLocationRestrictions(location)) {
                blockDownloads();
            }
        } else {
            console.warn('Could not determine user location');
        }
        userLocationChecked = true;
    })
    .catch(error => {
        console.error('All geolocation services failed:', error);
        userLocationChecked = true;
    });
}

// 页面加载时初始化地理定位检查
$(document).ready(function() {
    getUserLocation();
});
