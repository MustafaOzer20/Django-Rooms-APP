from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import (
    CreateView, 
    ListView, 
    DetailView, 
    TemplateView, 
    UpdateView,
    View
)

import random

from channels.helpers import get_page_data, is_exists
from channels.forms import CreateChannelForm, EditChannelForm, MessageForm
from channels.models import ChannelJoinRequest, Channels, ChannelsMembership

# Create your views here.

class WelcomeView(TemplateView):
    template_name = 'home.html'

class CreateChannelView(LoginRequiredMixin, CreateView):
    model = Channels
    form_class = CreateChannelForm
    template_name = 'channels/create.html'
    success_url = '/channels/my-channels-list'

    def form_valid(self, form):
        channel = form.save(commit=False)
        channel.admin_user = self.request.user
        channel.save()

        ChannelsMembership.objects.create(user=self.request.user, channel=channel)

        return super().form_valid(form)


class EditChannelView(LoginRequiredMixin, UpdateView):
    model = Channels
    form_class = EditChannelForm 
    template_name = 'channels/edit.html'
    success_url = '/channels/my-channels-list'

    def form_valid(self, form):
        channel = form.save(commit=False)
        if channel.is_private is False:
            join_requests = ChannelJoinRequest.objects.filter(channel=channel)
            for join_request in join_requests:
                ChannelsMembership.objects.create(user=join_request.user, channel=channel)
                join_request.delete()
            messages.success(self.request, "Channel updated successfully. Join requests are processed.")
        else:
            messages.success(self.request, "Channel updated successfully.")
        channel.save()
        return super().form_valid(form)


    def get_object(self, queryset=None):
        return get_object_or_404(Channels, id=self.kwargs['channel_id'])
    
    def get_initial(self):
        channel = self.get_object()
        return {'title': channel.title, 'is_private': channel.is_private}
    
    def get_success_url(self):
        return reverse_lazy('channels:channel_detail', kwargs={'pk': self.kwargs['channel_id']})

class DeleteChannelView(LoginRequiredMixin, View):
    def post(self, request):
        channel_id = request.POST.get('channel_id')
        channel = get_object_or_404(Channels, id=channel_id)
        if request.user == channel.admin_user:
            channel.delete()
            messages.success(request, "Channel deleted successfully.")
        else:
            messages.error(request, "You are not authorized to delete this channel.")
        return redirect('channels:my_channels')

class MyChannelsListView(LoginRequiredMixin, ListView):
    model = ChannelsMembership
    template_name = 'channels/my_channels_list.html'
    context_object_name = 'memberships'
    paginate_by = 2

    def get_queryset(self):
        return ChannelsMembership.objects.filter(user=self.request.user).order_by('-joined_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        memberships = context['memberships']
        paginator = Paginator(memberships, self.paginate_by)
        page = self.request.GET.get('page')
        memberships = get_page_data(paginator, page)
        
        context['memberships'] = memberships
        return context
    
class ChannelDetailView(LoginRequiredMixin, DetailView):
    model = Channels
    template_name = 'channels/detail.html'
    context_object_name = 'channel'

    def get_context_data(self, **kwargs):
        channel = self.get_object()
        if self.request.user in channel.users.all():
            context = super().get_context_data(**kwargs)
            context['form'] = MessageForm()
            return context
        return None

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        channel = self.get_object()
        if self.request.user in channel.users.all():
            return super().get(request, *args, **kwargs)
        return redirect(reverse_lazy('channels:all_channels'))
    
    def post(self, request, *args, **kwargs):   
        form = MessageForm(request.POST)
        if form.is_valid():
            # Get the message from the form
            message = form.save(commit=False)
            message.user = request.user
            message.channel = self.get_object()
            message.save()
        return redirect(request.path_info) 
        
    

class ChannelsListView(ListView):
    model = Channels
    template_name = 'channels/channels_list.html'
    context_object_name = 'all_channels'
    paginate_by = 10

    def get_queryset(self):
        return Channels.objects.annotate(num_users=Count('users')).order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_channels = context['all_channels']
        paginator = Paginator(all_channels, self.paginate_by)
        page = self.request.GET.get('page')
        all_channels = get_page_data(paginator, page)
        
        context['all_channels'] = all_channels
        return context
    

class ChannelMemberListView(LoginRequiredMixin, ListView):
    template_name = 'channels/members_list.html'
    context_object_name = 'members'
    paginate_by = 10

    def get_queryset(self):
        channel_id = self.kwargs.get('channel_id')
        query = self.request.GET.get('q')
        if query:
            return ChannelsMembership.objects.filter(
                channel_id=channel_id, user__username__icontains=query
            ).select_related('user').order_by('-joined_at')
        else: 
            return ChannelsMembership.objects.filter(
                channel_id=channel_id
                ).select_related('user').order_by('-joined_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        channel_id = self.kwargs.get('channel_id')
        channel = get_object_or_404(Channels, pk=channel_id)
        
        members = context['members']
        paginator = Paginator(members, self.paginate_by)
        page = self.request.GET.get('page')
        members = get_page_data(paginator, page)

        context['members'] = members
        context['channel'] = channel
        return context
    

class JoinChannelRequestView(LoginRequiredMixin, View):
    def post(self, request):
        channel_id = request.POST.get('channel_id')
        try:
            channel = Channels.objects.get(id=channel_id)
        except Channels.DoesNotExist:
            messages.error(request, "Channel does'nt exist.")
            return redirect(reverse_lazy('channels:all_channels'))

        if not is_exists(model=ChannelsMembership, user=request.user, channel=channel):
            if not is_exists(model=ChannelJoinRequest, user=request.user, channel=channel):
                if channel.is_private:
                    ChannelJoinRequest.objects.create(user=request.user, channel=channel)
                    messages.success(request, "Your join request has been sent to the channel.")  
                    return redirect(reverse_lazy('channels:all_channels'))  
                else:
                    ChannelsMembership.objects.create(user=request.user, channel=channel)
                    messages.success(request, "You have successfully joined the channel.")
            else:
                messages.warning(request, "You have already sent a join request.")
                return redirect(reverse_lazy('channels:all_channels'))
        else:
            messages.warning(request, "You are already a member of this channel.")


        return redirect(reverse_lazy('channels:channel_detail', kwargs={'channel_id': channel.id}))


class ChannelJoinRequestListView(LoginRequiredMixin, ListView):
    model = ChannelJoinRequest
    template_name = 'channels/channel_join_requests.html'
    context_object_name = 'all_requests'
    paginate_by = 10

    def get_queryset(self):
        channel_id = self.kwargs['channel_id']
        return ChannelJoinRequest.objects.filter(
            channel_id=channel_id, 
            channel__admin_user=self.request.user
        ).order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_requests = context['all_requests']
        paginator = Paginator(all_requests, self.paginate_by)
        page = self.request.GET.get('page')
        all_requests = get_page_data(paginator, page)
        channel_id = self.kwargs['channel_id']
        context['all_requests'] = all_requests
        context['channel_id'] = channel_id
        return context
    
class JoinRequestDecisionView(LoginRequiredMixin, View):
    def post(self, request):
        request_id = request.POST.get('j_request_id')
        decision = request.POST.get('decision')

        join_request = get_object_or_404(ChannelJoinRequest, id=request_id)
        channel_id = join_request.channel.id
        if join_request.channel.admin_user == request.user:
            if decision == 'approve':
                ChannelsMembership.objects.create(
                    user=join_request.user, 
                    channel=join_request.channel
                )
                join_request.delete()
            elif decision == 'reject':
                join_request.delete()

        return redirect(reverse_lazy('channels:list_join_requests', kwargs={'channel_id': channel_id}))
    

class LeaveChannelView(LoginRequiredMixin, View):
    def post(self, request):
        channel_id = request.POST.get('channel_id')
        channel = get_object_or_404(Channels, id=channel_id)
        if is_exists(model=ChannelsMembership, user=request.user, channel=channel):
            if channel.admin_user == request.user:
                if channel.users.count() == 1:
                    channel.delete()
                    messages.success(request, "You have left the channel successfully.")
                    return redirect(reverse_lazy('channels:all_channels'))
                random_member = random.choice(channel.users.exclude(id=request.user.id))
                channel.admin_user = random_member
                channel.save()
            membership = ChannelsMembership.objects.get(channel=channel, user=request.user)
            membership.delete()
            messages.success(request, "You have left the channel successfully.")
        else:
            messages.error(request, "You are not already a member of this channel.")
        return redirect(reverse_lazy('channels:all_channels'))