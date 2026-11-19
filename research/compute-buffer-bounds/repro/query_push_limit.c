#include <stdio.h>
#include <dlfcn.h>
#define VK_ENABLE_BETA_EXTENSIONS
#include <vulkan/vulkan.h>
int main(int c,char**v){
 void*h=dlopen(v[1],RTLD_NOW); if(!h){printf("dlopen %s\n",dlerror());return 1;}
 PFN_vkGetInstanceProcAddr gipa=dlsym(h,"vkGetInstanceProcAddr");
 PFN_vkCreateInstance ci=(void*)gipa(0,"vkCreateInstance");
 VkApplicationInfo ai={VK_STRUCTURE_TYPE_APPLICATION_INFO,0,"q",0,"q",0,VK_API_VERSION_1_3};
 const char* ex[]={"VK_KHR_portability_enumeration","VK_KHR_get_physical_device_properties2"};
 VkInstanceCreateInfo ici={VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,0,0,&ai,0,0,0,ex};
 VkInstance inst; VkResult r=ci(&ici,0,&inst); if(r){printf("ci %d\n",r);return 1;}
 PFN_vkEnumeratePhysicalDevices epd=(void*)gipa(inst,"vkEnumeratePhysicalDevices");
 uint32_t n=1; VkPhysicalDevice pd; epd(inst,&n,&pd);
 PFN_vkGetPhysicalDeviceProperties2 gp=(void*)gipa(inst,"vkGetPhysicalDeviceProperties2");
 VkPhysicalDevicePushDescriptorPropertiesKHR pp={VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PUSH_DESCRIPTOR_PROPERTIES_KHR};
 VkPhysicalDeviceProperties2 p2={VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2,&pp};
 gp(pd,&p2);
 printf("%s api %u.%u maxPushDescriptors=%u maxPerStageResources=%u maxPerStageDescriptorStorageBuffers=%u\n",p2.properties.deviceName,VK_VERSION_MAJOR(p2.properties.apiVersion),VK_VERSION_MINOR(p2.properties.apiVersion),pp.maxPushDescriptors,p2.properties.limits.maxPerStageResources,p2.properties.limits.maxPerStageDescriptorStorageBuffers);
 return 0;}
